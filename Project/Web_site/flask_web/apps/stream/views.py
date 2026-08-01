import cv2
import torch

from flask import (
    Blueprint,
    Response,
    render_template,
    render_template_string,
    url_for
)

stream=Blueprint(
    "stream",
    __name__,
    template_folder="templates",
    static_folder="static"
)

model=torch.hub.load('ultralytics/yolov5', 'yolov5s', pretrained=True)

video_path='c:/DW/workspaces/python_AI/video/01.mp4'

cap=cv2.VideoCapture(video_path)

@stream.route("/")
def index():
    html_template = """
    <html>
        <head><title>YOLOv5 Live Streaming</title></head>
        <body style="text-align: center; background-color: #222; color: white;">
            <h1>YOLOv5 실시간 객체 탐지 스트리밍</h1>
            <div>
                <img src="{{ url_for('stream.video_feed') }}" width="800" style="border: 2px solid #fff;"/>
            </div>
        </body>
    </html>
    """
    return render_template_string(html_template)

@stream.route("/video_feed")
def video_feed():
    return Response(
        execute_detect(), mimetype="multipart/x-mixed-replace; boundary=frame"
    )

def execute_detect():
    while True:
        success, frame=cap.read()
        if not success:
            break
        else:
            rgb_frame=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
            results=model(rgb_frame)
            annotated_frame=results.render()[0]

            annotated_frame=cv2.cvtColor(annotated_frame, cv2.COLOR_RGB2BGR)

            ret, buffer=cv2.imencode(".jpg", annotated_frame)
            frame_bytes=buffer.tobytes()

            yield(
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"+frame_bytes+b"\r\n"
            )