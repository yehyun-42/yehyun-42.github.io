import cv2
import time
import sqlite3
import threading
from ultralytics import YOLO
from flask import Blueprint, Response, render_template, render_template_string, url_for, redirect, jsonify
import requests

import smtplib  # 💡 이메일 발송 라이브러리
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv

from apps.extensions import db
from apps.db_test.project_db import User, Animals, Detect_animal, Dangers
from datetime import datetime

from apps.buzzer_helper import trigger_animal_sound, trigger_danger_sound

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

stream = Blueprint(
    "stream",
    __name__,
    template_folder="templates",
    static_folder="static",
)

# [구조 변경] 동물별로 관리해야 하는 '최소 기준 마리수' 정의
TARGET_ANIMALS = {"dog": 0, "cat": 0}
ANIMAL_NAME_MAP = {"dog": "개", "cat": "고양이"}
def update_target_animals_from_db():
    global TARGET_ANIMALS
    try:
        conn = sqlite3.connect(DB_FILE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT animal_type, animal_count FROM animals")
        records = cursor.fetchall()
        
        new_targets = {}
        for row in records:
            animal_type, animal_count = row
            new_targets[animal_type] = animal_count
            
        conn.close()
        if new_targets:
            TARGET_ANIMALS = new_targets
            print(f"🔄 [DB 동기화 완료] 현재 기준 타겟: {TARGET_ANIMALS}")
    except Exception as e:
        print(f"❌ [DB 동기화 실패]: {e}")
        if not TARGET_ANIMALS:
            TARGET_ANIMALS = {"dog": 0, "cat": 0}

# ─── 위험 객체 임시 저장을 위한 전역 큐 및 락 설정 ───
danger_buffer = []
buffer_lock = threading.Lock()

# 💡 [추가] 위험 객체별 개별 10초 쿨다운을 위한 타임스탬프 딕셔너리
anomaly_target = {"blue_alien": "외계인", "blue_shark": "상어", "pink_dragon": "용", "tiger": "호랑이"}
last_danger_detected_time = {k: 0 for k in anomaly_target.keys()}

DANGER_COOLDOWN = 10.0  # 10초 쿨다운 설정
DB_FILE_PATH = "C:/project_team3/workspaces/project_SSA/local.sqlite" 

VIDEO_SOURCES = {
    "video_1": "C:/project_team3/workspaces/project_SSA/videos/streaming_0.mp4",
    "video_2": "C:/project_team3/workspaces/project_SSA/videos/streaming_2.mp4", # 기존 파일
    "video_3": "C:/project_team3/workspaces/project_SSA/videos/streaming_5.mp4",
}

video_path = VIDEO_SOURCES["video_1"]

cap = None

@stream.route("/change_source/<source_key>")
def change_video_source(source_key):
    global video_path, cap
    
    clean_key = str(source_key).strip().lower()
    
    # 1. 전역 변수 video_path 값만 단순하게 즉시 변경
    if "video_1" in clean_key:
        video_path = VIDEO_SOURCES["video_1"]
    elif "video_3" in clean_key:
        video_path = VIDEO_SOURCES["video_3"]
    else:
        video_path = VIDEO_SOURCES["video_2"] # 기본값 (video_2)

    # 2. 기존 캡처 객체를 확실하게 릴리즈하여 백그라운드 스레드가 완전히 새 경로를 읽도록 유도
    if cap is not None:
        try:
            cap.release()
        except:
            pass
    cap = None  # 스레드 루프 내 'if cap is None:' 분기가 실행되도록 None 처리
    
    print(f"🎯 [백엔드 경로 변경] 웹창 새로고침 유도 -> {video_path}")
    
    # 3. ✨ [핵심] 경로 변경 완료 후 메인 관제 페이지로 화면을 강제 새로고침(리다이렉트) 시킵니다!
    return redirect(url_for('stream.index'))

update_target_animals_from_db()

# 실시간 스트리밍을 위한 전역 변수
current_frame = None
is_running = True  
active_connections = 0 

# 독립된 두 함수가 공유할 전역 변수들 배치
program_start_time = time.time()
start_time = None
is_timer_running = False

# 다중 동물 타이머 누적용 변수 초기화
max_counts = {animal: 0 for animal in TARGET_ANIMALS}
last_verified_counts = {animal: 0 for animal in TARGET_ANIMALS}
db_save_time = time.time()
ALARM_COOLDOWN = 10.0
last_alarm_time = {animal: 0 for animal in TARGET_ANIMALS}

@stream.route("/")
def index():
    # 웹 브라우저가 열릴 때(메인 스레드), 누적된 위험 객체 버퍼를 한 번에 DB로 비워줍니다.
    sync_danger_buffer_to_db()

    update_target_animals_from_db()
    total_animal_count=sum(TARGET_ANIMALS.values())
    danger_count = Dangers.query.count()
    animal_detect=Detect_animal.query.count()
    
    # templates 디렉토리 내부의 상대 경로를 지정하여 깔끔하게 파일 랜더링
    return render_template("index.html",
                           animal_count=total_animal_count,
                           danger_detect=danger_count,
                           animal_detect=animal_detect)


# ─── 임시 버퍼 데이터를 SQLAlchemy를 통해 DB로 집어넣는 순수 핵심 로직 ───
def sync_danger_buffer_to_db():
    global danger_buffer
    
    with buffer_lock:
        if not danger_buffer:
            return 0
        # 현재까지 쌓인 버퍼 복사 후 초기화 (Thread-safe)
        batch_to_save = list(danger_buffer)
        danger_buffer.clear()
        
    saved_count = 0
    for item in batch_to_save:
        # 💡 [변경] Dangers 모델 구조에 맞춤 (danger_spec 전달, danger_detect는 버퍼의 생성된 datetime 객체 전달)
        new_danger = Dangers(
            danger_spec=item["object_name"],
            danger_detect=item["detected_at"]
        )
        db.session.add(new_danger)
        saved_count += 1
        
    if saved_count > 0:
        try:
            db.session.commit()
            print(f"📊 [SQLAlchemy] 임시 큐에서 {saved_count}개의 위험 데이터를 꺼내 DB 추가 성공!")
        except Exception as e:
            db.session.rollback()
            print(f"❌ [SQLAlchemy] 임시 큐 적재 중 오류 발생: {e}")
    return saved_count

alarm_state = {animal: False for animal in TARGET_ANIMALS}
under_target_start_time = {animal: None for animal in TARGET_ANIMALS}
recovery_start_time = {animal: None for animal in TARGET_ANIMALS}

def process_animal_detection_logic(boxes, names):
    """YOLO 감지 결과를 받아 실시간 미달/이상 판정(SQLite 전용)"""
    global program_start_time, TARGET_ANIMALS, max_counts, last_verified_counts, db_save_time, ALARM_COOLDOWN, last_alarm_time, under_target_start_time, recovery_start_time

    # 상자 인덱싱 오류 방지를 위한 안전한 구조 유지
    detected_names = []
    
    # [보완] boxes 내부 데이터 유무를 개수(len)까지 완벽히 체크
    if boxes is not None and len(boxes) > 0:
        for i in range(len(boxes)):
            try:
                box = boxes[i] 
                if len(box.conf) == 0: 
                    continue
                
                conf = box.conf[0].item()
                if conf >= 0.5:  # 원하는 conf 수치로 변경 가능
                    if len(box.cls) > 0:
                        cls_id = int(box.cls[0].item())
                        detected_names.append(names[cls_id])
            except Exception as e:
                # 개별 박스 처리 중 에러가 나도 웹 스트리밍이 안 죽도록 방어
                continue
                
    current_time = time.time()
    
    is_stable = (current_time - program_start_time) >= 3.0
    db_elapsed_time = current_time - db_save_time
    
    if is_stable:
        for animal, target_count in TARGET_ANIMALS.items():
            current_count = detected_names.count(animal)
            status = None

            if current_count < target_count:
                recovery_start_time[animal] = None
                if under_target_start_time[animal] is None:
                    under_target_start_time[animal] = current_time
                    print(f"⏰ [{animal}] 미달 최초 감지! 10초 측정을 시작합니다.")
                elif (current_time - under_target_start_time[animal]) >= 10.0 and is_stable:
                    status = "미달"
            else:
                if under_target_start_time[animal] is not None:
                    if recovery_start_time[animal] is None:
                        recovery_start_time[animal] = current_time
                    elif (current_time - recovery_start_time[animal]) >= 2.5:
                        under_target_start_time[animal] = None
                        recovery_start_time[animal] = None
                        print(f"✅ [{animal}] 2.5초간 정상 수량 안정적 유지 -> 타이머 완전히 초기화.")
                else:
                    recovery_start_time[animal] = None

            if status is not None:
                if current_count < target_count:
                    status = "미달"
                
                if status is not None:
                    if current_time - last_alarm_time.get(animal, 0) >= ALARM_COOLDOWN:
                        last_alarm_time[animal] = current_time
                        korean_name = ANIMAL_NAME_MAP.get(animal, animal)
                        type_string = f"{korean_name}({status})"
                        
                        print(f"🚨 [경보] 위험! {animal} 개체수 10초간 {status} 지속! 현재: {current_count}마리")
                        
                        try:
                            conn = sqlite3.connect(DB_FILE_PATH)
                            cursor = conn.cursor()
                            current_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            
                            sql = """INSERT INTO detect_animal (detect_type_count, detect_animal_count, detect_day, detect_alarm) VALUES (?, ?, ?, ?)"""
                            
                            sound_thread = threading.Thread(target=trigger_animal_sound, daemon=True)
                            sound_thread.start()

                            if status == "미달":
                                email_thread = threading.Thread(target=send_alert_email, args=(animal,), daemon=True)
                                email_thread.start()
                            
                                discord_thread = threading.Thread(target=send_discord_webhook, args=(type_string,), daemon=True)
                                discord_thread.start()

                            cursor.execute(sql, (type_string, current_count, current_now, True))
                            conn.commit()
                            conn.close()
                            print(f"💾 [DB 긴급저장 완료] 상태: {type_string}")
                        except Exception as e:
                            print(f"❌ [DB 긴급저장 오류]: {e}")

    # 10분 주기 최대값 카운트 갱신 로직
    for animal in TARGET_ANIMALS.keys():
        current_count = detected_names.count(animal)
        if current_count > max_counts.get(animal, 0):
            max_counts[animal] = current_count

    # 10분 주기 정기 DB 저장 로직
    if db_elapsed_time >= 20.0:
        detected_animals = []
        for k, v in max_counts.items():
            if v > 0:
                korean_name = ANIMAL_NAME_MAP.get(k, k) 
                detected_animals.append(f"{korean_name}:{v}마리")
        
        total_count = sum(max_counts.values())
        
        if detected_animals:
            is_periodic_alarm = any(max_counts.get(a, 0) != TARGET_ANIMALS.get(a, 0) for a in TARGET_ANIMALS)
            try:
                conn = sqlite3.connect(DB_FILE_PATH)
                cursor = conn.cursor()
                current_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                sql = """INSERT INTO detect_animal (detect_type_count, detect_animal_count, detect_day, detect_alarm) VALUES (?, ?, ?, ?)"""
                type_string = ", ".join(detected_animals)
                
                cursor.execute(sql, (type_string, total_count, current_now, is_periodic_alarm))
                conn.commit()
                conn.close()
                print(f"💾 [DB 정기저장 완료] 수량: {type_string}")

                threading.Thread(target=send_alert_email, args=(animal,), daemon=True).start()
                threading.Thread(target=send_discord_webhook, args=(type_string,), daemon=True).start()

            except Exception as e:
                print(f"❌ [DB 정기저장 오류]: {e}")
        
        last_verified_counts = max_counts.copy()
        update_target_animals_from_db()
        db_save_time = time.time()
        
        # [개선] 전역 딕셔너리 객체를 완전히 새로 대입하지 않고 내부 값만 안전하게 0으로 초기화
        for animal in TARGET_ANIMALS:
            max_counts[animal] = 0

def save_abnormal_objects_to_buffer(boxes, names):
    """YOLO 탐지 결과 중 외계인, 상어, 용만 필터링하여 전역 딕셔너리 버퍼에 임시 누적 (객체별 10초 쿨다운 적용)"""
    global danger_buffer, last_danger_detected_time, DANGER_COOLDOWN
    
    detected_names = []
    for box in boxes:
        if box.conf[0].item()>=0.5:
            detected_names.append(names[int(box.cls[0])])
    current_time = time.time()

    newly_detected = []
    
    for model_class_name, korean_name in anomaly_target.items():
        if model_class_name in detected_names:
            if current_time - last_danger_detected_time.get(model_class_name, 0) >= DANGER_COOLDOWN:
                newly_detected.append(korean_name)
                last_danger_detected_time[model_class_name] = current_time
        
    if newly_detected:
        with buffer_lock:
            danger_buffer.append({
                "object_name": ", ".join(newly_detected), # 예: "외계인, 상어"
                "detected_at": datetime.now()
            })
        trigger_danger_sound()

        alert_message = ", ".join(newly_detected)

        email_thread = threading.Thread(target=send_alert_email, args=(alert_message,), daemon=True)
        email_thread.start()
        
        discord_thread = threading.Thread(target=send_discord_webhook, args=(alert_message,), daemon=True)
        discord_thread.start()
        
        print(f"📥 [버퍼 저장] 감지된 위험 요소: {', '.join(newly_detected)}")

    

def video_capture_and_detect(): 
    """비디오를 읽어 YOLOv12 감지, 동물 수 체크, 버퍼 축적을 수행하는 독립 백그라운드 스레드"""
    global current_frame, is_running, video_path, cap, program_start_time

    program_start_time = time.time()

    # model_path = "C:/project_team3/workspaces/project_SSA/runs/detect/my_yolov12_project/yolov12s_custom/weights/best.pt"
    model_path = "C:/project_team3/workspaces/project_SSA/runs/detect/my_yolov12_project/yolov8n_train-6/weights/best.pt"
    model = YOLO(model_path) 
    try:
        while True:
            # 1. 접속자가 없으면 비디오 캡처를 해제하고 1초간 쉬며 대기 (YOLO 감지 건너뜀)
            if active_connections <= 0:
                if cap is not None:
                    try:
                        cap.release()
                    except:
                        pass
                    cap = None
                    print("[알림] 유저 이탈: 감지 및 스트리밍을 일시 중지합니다.")
                time.sleep(1.0) # 대기 시간 증가로 CPU 소모 방지
                continue # 루프의 처음으로 돌아가 다음 접속자를 체크함
                
            if cap is None:
                print("[알림] 유저 진입: ESP32-Cam 스트림 연결을 시도합니다.")
                cap = cv2.VideoCapture(video_path)
                
            if cap.isOpened():
                # [개선 3] 스트림 장치 연결이 성공하고 화면을 받기 시작하는 순간에 프로그램 시작 시점을 리셋합니다.
                # 이 코드로 인해 영상이 채 켜지기도 전에 허위 미달 알람이 먼저 발생하는 버그가 차단됩니다.
                
                
                # OpenCV 내부 버퍼 크기 제한 (밀린 프레임 버리기 최적화 유지)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                fps = cap.get(cv2.CAP_PROP_FPS)
                if fps <= 0 or float('-inf') < fps < float('inf') is False: 
                    fps = 30.0
                frame_delay = 1.0 / fps
 
            if not cap.isOpened():
                print(f"[-] 에러: 영상 스트림({video_path})에 연결할 수 없습니다. 재시도 중...")
                time.sleep(1.0)
                continue
                
            start_loop_time = time.time() 
 
            if cap.get(cv2.CAP_PROP_BUFFERSIZE) > 0:
                for _ in range(2): 
                    cap.grab()
 
            success, frame = cap.read()
            if not success:
                cap.release()
                cap = cv2.VideoCapture(video_path) 
                time.sleep(0.03)
                continue
                
            if not is_running:
                time.sleep(0.03)
                continue
                
            results = model(frame, conf=0.50, verbose=False)
 
            boxes = results[0].boxes
            names = results[0].names
 
            process_animal_detection_logic(boxes, names)
            save_abnormal_objects_to_buffer(boxes, names)
 
            annotated_frame = results[0].plot()
            current_frame = annotated_frame
            
            compute_time = time.time() - start_loop_time
            remain_delay = frame_delay - compute_time
            if remain_delay > 0:
                time.sleep(remain_delay) 
    finally:
        if cap is not None:
            cap.release()


def send_alert_email(alert_message):
    smtp_server = "smtp.gmail.com"
    smtp_port = 465  
    sender_email = "dhkang8817@gmail.com"
    sender_password = "pqzuqioaxemrsuml"

    if alert_message in TARGET_ANIMALS:
        try:
            conn = sqlite3.connect(DB_FILE_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT email FROM users WHERE role = 'standby'")
            records = cursor.fetchall()
            conn.close()

            receiver_email = [row[0] for row in records]
            if not receiver_email:
                return

            subject = f"[경보] 개체수 미달 감지 알림"
            body = f"관리자님,\n\n현재 개체수 미달이 감지되었습니다: {alert_message}\n시스템을 확인해 주세요."
            
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = sender_email
            msg['To'] = ", ".join(receiver_email)

            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
            server.quit()
            print(f"📧 [이메일 성공] 관리자에게 {alert_message} 알림 메일을 전송했습니다.")
        except Exception as e:
            print(f"❌ [이메일 실패] 메일 발송 중 오류 발생: {e}")
    if alert_message in anomaly_target:
        try:
            conn = sqlite3.connect(DB_FILE_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT email FROM users WHERE role = 'standby'")
            records = cursor.fetchall()
            conn.close()

            receiver_email = [row[0] for row in records]
            if not receiver_email:
                return

            subject = f"[경보] 이상객체 감지 알림"
            body = f"관리자님,\n\n현재 {alert_message} 위험이 감지되었습니다: \n시스템을 확인해 주세요."
            
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = sender_email
            msg['To'] = ", ".join(receiver_email)

            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
            server.quit()
            print(f"📧 [이메일 성공] 관리자에게 {alert_message} 알림 메일을 전송했습니다.")
        except Exception as e:
            print(f"❌ [이메일 실패] 메일 발송 중 오류 발생: {e}")

detection_thread = threading.Thread(target=video_capture_and_detect, daemon=True)
detection_thread.start()


def generate_frames():
    global current_frame, active_connections, video_path, cap 
    
    active_connections += 1
    print(f"[+] 브라우저 연결됨 (현재 접속자 수: {active_connections}명)")
    try:
        while True:
            if current_frame is not None:
                ret, buffer = cv2.imencode(".jpg", current_frame)
                if not ret:
                    continue
                frame_bytes = buffer.tobytes()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                )
                time.sleep(0.03) 
            else:
                time.sleep(0.03)
    except GeneratorExit:
        pass
    finally:
        active_connections -= 1
        print(f"[-] 브라우저 연결 끊김 (현재 접속자 수: {active_connections}명)")


@stream.route("/video_feed")
def video_feed():
    return Response(generate_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

@stream.route("/sync_dangers")
def sync_dangers():
    synced_count = sync_danger_buffer_to_db()
    recent_animal_alerts = []
    try:
        conn = sqlite3.connect(DB_FILE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT detect_type_count, detect_animal_count, detect_day 
            FROM detect_animal 
            WHERE detect_alarm = 1 
            ORDER BY detect_day DESC LIMIT 10
        """)
        records = cursor.fetchall()
        conn.close()
         
        # 이 반복문 안의 형식을 인덱스 번호([0],[1],[2])가 들어간 구조로 변경합니다.
        for row in records:
            recent_animal_alerts.append({
                "type": row[0],    # 개체종류(상태) ex) 개(미달)
                "count": row[1],   # 현재 수량
                "time": row[2]     # 감지 시간
            })
    except Exception as e:
        print(f"❌ [프론트엔드 연동용 DB 조회 실패]: {e}")
        
    return jsonify({
        "status": "success",
        "synced_count": synced_count,
        "animal_alerts": recent_animal_alerts
    })

load_dotenv()

def send_discord_webhook(message):
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    data = {
        "content": f"🚨 [보호센터 알람]: {message}",
        "username": "보호센터 AI 감지기"
    }
    try:
        requests.post(webhook_url, json=data)
    except Exception as e:
        print(f"디스코드 발송 오류: {e}")