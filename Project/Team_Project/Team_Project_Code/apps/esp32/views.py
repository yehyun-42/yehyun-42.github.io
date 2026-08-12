import threading
import time
import warnings
import cv2
import numpy as np  # ✅ 추가
import torch
from ultralytics import YOLO
from flask import Blueprint, Response, render_template
from apps.stream.views import (
    TARGET_ANIMALS, DB_FILE_PATH, 
    process_animal_detection_logic, update_target_animals_from_db, save_abnormal_objects_to_buffer
)
from apps.extensions import db
from apps.db_test.project_db import Dangers, Detect_animal
import os
import sys
import requests

warnings.filterwarnings("ignore", category=FutureWarning)

esp32_yolov12 = Blueprint(
    "esp32_yolov12",
    __name__,
    template_folder="templates",
    static_folder="static",
)

ESP32_STREAM_URL = "http://192.168.137.140/stream"
TARGET_ANIMALS = TARGET_ANIMALS
DB_FILE_PATH = DB_FILE_PATH

# 공유 변수
encoded_frame = None
is_running = True
frame_lock = threading.Lock()
stream_connection = None  # ✅ 전역 연결 관리

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp"

@esp32_yolov12.route("/")
def index():
    update_target_animals_from_db()
    total_animal_count = sum(TARGET_ANIMALS.values())
    danger_count = Dangers.query.count()
    animal_detect = Detect_animal.query.count()
    return render_template("esp32/index.html",
                           animal_count=total_animal_count,
                           danger_detect=danger_count,
                           animal_detect=animal_detect)

model = None

def generate_frames():
    global model, is_running, stream_connection
    print("[DEBUG] generate_frames 시작", file=sys.stderr)
    
    try:
        if model is None:
            model = YOLO("C:/project_team3/workspaces/project_SSA/runs/detect/my_yolov12_project/yolov8n_train-6/weights/best.pt")
        
        # ✅ 연결 재시도
        stream_connection = connect_esp32_stream(max_retries=5)
        
        if stream_connection is None:
            print("[ERROR] ESP32 스트림 연결 최종 실패", file=sys.stderr)
            # ✅ 더미 프레임 반환 (오류 표시)
            dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(dummy_frame, "ESP32 Connection Failed", (50, 240),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            _, buffer = cv2.imencode('.jpg', dummy_frame)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + 
                   buffer.tobytes() + b'\r\n')
            return
        
        bytes_buffer = b''
        
        for chunk in stream_connection.iter_content(chunk_size=1024):
            if not chunk:
                print("[WARNING] 스트림 청크 수신 실패, 재연결 시도", file=sys.stderr)
                stream_connection = connect_esp32_stream(max_retries=3)
                if stream_connection is None:
                    break
                continue
            
            bytes_buffer += chunk
            
            # JPEG 경계 찾기
            a = bytes_buffer.find(b'\xff\xd8')
            b = bytes_buffer.find(b'\xff\xd9')
            
            if a != -1 and b != -1 and b > a:
                frame_data = bytes_buffer[a:b+2]
                bytes_buffer = bytes_buffer[b+2:]
                
                if len(bytes_buffer) > 1024 * 1024:
                    print("[WARNING] 바이트 버퍼 초기화", file=sys.stderr)
                    bytes_buffer = b''
                
                frame = cv2.imdecode(np.frombuffer(frame_data, dtype=np.uint8), 
                                   cv2.IMREAD_COLOR)
                
                if frame is not None:
                    # YOLO 감지
                    results = model.predict(source=frame, conf=0.5, verbose=False)
                    
                    if results and results[0].boxes:
                        process_animal_detection_logic(results[0].boxes, model.names)
                        save_abnormal_objects_to_buffer(results[0].boxes, model.names)
                        annotated_frame = results[0].plot()
                    else:
                        annotated_frame = frame
                    
                    _, buffer = cv2.imencode('.jpg', annotated_frame,
                                            [cv2.IMWRITE_JPEG_QUALITY, 80])
                    jpeg_bytes = buffer.tobytes()
                    
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + 
                           jpeg_bytes + b'\r\n')
    
    except Exception as e:
        print(f"[ERROR] generate_frames 예외: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    
    finally:
        if stream_connection:
            try:
                stream_connection.close()
            except:
                pass

def connect_esp32_stream(max_retries=3):
    """✅ ESP32 스트림 연결"""
    global stream_connection
    
    for attempt in range(max_retries):
        try:
            print(f"[DEBUG] ESP32 스트림 연결 시도 {attempt + 1}/{max_retries}", 
                  file=sys.stderr)
            
            if stream_connection:
                try:
                    stream_connection.close()
                except:
                    pass
            
            # ✅ 타임아웃 짧게 설정
            stream_connection = requests.get(
                ESP32_STREAM_URL,
                stream=True,
                timeout=5,  # 5초로 단축
                allow_redirects=False
            )
            
            print(f"[DEBUG] 응답 코드: {stream_connection.status_code}", file=sys.stderr)
            
            if stream_connection.status_code == 200:
                print("[DEBUG] ESP32 스트림 연결 성공", file=sys.stderr)
                return stream_connection
        
        except requests.exceptions.Timeout:
            print(f"[ERROR] 타임아웃 (시도 {attempt + 1}/{max_retries})", file=sys.stderr)
        except requests.exceptions.ConnectionError as e:
            print(f"[ERROR] 연결 거부: {e} (시도 {attempt + 1}/{max_retries})", file=sys.stderr)
        except Exception as e:
            print(f"[ERROR] {e} (시도 {attempt + 1}/{max_retries})", file=sys.stderr)
        
        if attempt < max_retries - 1:
            time.sleep(2)
    
    return None

@esp32_yolov12.route('/video_feed')
def video_feed():
    print("[DEBUG] /video_feed 접근", file=sys.stderr)
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')
