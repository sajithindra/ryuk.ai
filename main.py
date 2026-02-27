from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import cv2
import numpy as np
import threading
import uvicorn
import socket
import sys
import time
from collections import deque
from insightface.app import FaceAnalysis

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QFrame, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QImage, QPixmap, QFont, QPainter, QPen, QColor, QBrush
import qdarktheme

app = FastAPI()

print("Initializing InsightFace model...")
# Initialize InsightFace analysis. We specify ctx_id=0 to try using GPU for fast inference.
face_app = FaceAnalysis(name='buffalo_l')
face_app.prepare(ctx_id=0, det_size=(640, 640))
print("InsightFace model initialized successfully.")

# Thread-safe queue: maxlen=2 keeps only the latest frames, discarding stale ones
frame_queue = deque(maxlen=2)

@app.websocket("/ws/stream")
async def websocket_camera_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Camera client connected to /ws/stream")
    try:
        while True:
            data = await websocket.receive_bytes()
            frame_queue.append(data)
    except WebSocketDisconnect:
        print("Camera client disconnected")
    except Exception as e:
        print(f"Error reading camera websocket: {e}")

@app.get("/")
def read_root():
    return {"message": "Ryuk AI - Streaming Server Running. Connect camera to /ws/stream."}


def run_server(host: str):
    """Runs the uvicorn server in a background thread."""
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

class VideoProcessor(QThread):
    """
    Background Thread that reads from the frame queue, runs InsightFace detection,
    draws bounding boxes, and emits the processed QImage to the GUI.
    """
    frame_ready = pyqtSignal(QImage)
    stream_inactive = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.running = True

    def run(self):
        last_frame_time = 0
        is_active = False

        while self.running:
            if frame_queue:
                data = frame_queue.popleft()
                nparr = np.frombuffer(data, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if frame is not None:
                    last_frame_time = time.time()
                    if not is_active:
                        is_active = True
                        
                    # Rotate 90 degrees counter-clockwise to fix left-rotated mobile streams
                    frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

                    # Process frame with InsightFace (runs on background thread, avoids UI block)
                    faces = face_app.get(frame)
                    
                    # Iterate through detected faces and draw bounding boxes and landmarks
                    for face in faces:
                        bbox = face.bbox.astype(int)
                        cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
                        
                        if hasattr(face, 'kps') and face.kps is not None:
                            kps = face.kps.astype(int)
                            for kp in kps:
                                cv2.circle(frame, (kp[0], kp[1]), 2, (0, 0, 255), 2)

                    # Convert the processed OpenCV BGR image to RGB for QImage
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_frame.shape
                    bytes_per_line = ch * w
                    # Create QImage pointing to rgb_frame data
                    qt_img = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                    
                    # Emit a copy so the underlying numpy buffer isn't overwritten before Qt draws it
                    self.frame_ready.emit(qt_img.copy())
            else:
                # Check for timeout if no new frames have arrived
                if is_active and (time.time() - last_frame_time > 1.0):
                    is_active = False
                    self.stream_inactive.emit()
            
            # Tiny sleep to yield thread if queue is empty
            self.msleep(5)

    def stop(self):
        self.running = False
        self.wait()


class DashboardWindow(QMainWindow):
    def __init__(self, ip_address):
        super().__init__()
        self.ip_address = ip_address
        self.setWindowTitle("Ryuk AI - Dashboard")
        self.resize(1100, 700)
        
        # Main Layout
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.setCentralWidget(main_widget)

        # ----------------- SIDEBAR -----------------
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(250)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(20, 30, 20, 30)
        sidebar_layout.setSpacing(15)

        # Logo / Title
        title_label = QLabel("RYUK AI")
        title_font = QFont("Inter", 18, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #00E5FF; letter-spacing: 2px;")
        
        subtitle_label = QLabel("Live Detection System")
        subtitle_label.setStyleSheet("color: #8A92A6; font-size: 11px;")
        
        # Sidebar Menu Buttons
        self.btn_cameras = QPushButton("Devices")
        self.btn_cameras.setObjectName("SidebarBtnActive")
        self.btn_cameras.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.btn_reports = QPushButton("Reports / Activity")
        self.btn_reports.setObjectName("SidebarBtn")
        self.btn_reports.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.setObjectName("SidebarBtn")
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)

        # Status Info
        status_label = QLabel(f"Server:\nws://{self.ip_address}:8000/ws/stream")
        status_label.setWordWrap(True)
        status_label.setStyleSheet("color: #4CAF50; font-size: 11px; margin-top: 20px; padding: 10px; background: rgba(76, 175, 80, 0.1); border-radius: 8px;")

        sidebar_layout.addWidget(title_label)
        sidebar_layout.addWidget(subtitle_label)
        sidebar_layout.addSpacing(30)
        sidebar_layout.addWidget(self.btn_cameras)
        sidebar_layout.addWidget(self.btn_reports)
        sidebar_layout.addWidget(self.btn_settings)
        sidebar_layout.addStretch()
        sidebar_layout.addWidget(status_label)

        # ----------------- MAIN CONTENT -----------------
        self.content_area = QFrame()
        self.content_area.setObjectName("ContentArea")
        content_layout = QVBoxLayout(self.content_area)
        content_layout.setContentsMargins(40, 40, 40, 40)
        content_layout.setSpacing(20)

        header_label = QLabel("Active Camera Stream")
        header_font = QFont("Inter", 24, QFont.Weight.Bold)
        header_label.setFont(header_font)
        
        # Video Display Label
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setObjectName("VideoLabel")
        self.video_label.setMinimumSize(640, 480)
        
        self.set_inactive_ui()

        # Container for video to add some styling/border
        video_container = QFrame()
        video_container.setObjectName("VideoContainer")
        vc_layout = QVBoxLayout(video_container)
        vc_layout.setContentsMargins(10, 10, 10, 10)
        vc_layout.addWidget(self.video_label, alignment=Qt.AlignmentFlag.AlignCenter)

        content_layout.addWidget(header_label)
        content_layout.addWidget(video_container, 1) # Give it stretch factor

        # Add everything to main layout
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.content_area, 1)

        # Apply Stylesheet
        self.apply_styles()

        # Start Video Processor Thread
        self.video_processor = VideoProcessor()
        self.video_processor.frame_ready.connect(self.update_video_frame)
        self.video_processor.stream_inactive.connect(self.set_inactive_ui)
        self.video_processor.start()

    def update_video_frame(self, qt_img):
        """Called safely on GUI thread when a new frame is ready."""
        # Scale the image, keeping aspect ratio, to fit the video label's available size.
        scaled_img = qt_img.scaled(
            self.video_label.size(), 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation
        )
        self.video_label.setPixmap(QPixmap.fromImage(scaled_img))

    def set_inactive_ui(self):
        """Draws a mobile device with a red dot recursively indicating inactive status."""
        w, h = 640, 480
        pixmap = QPixmap(w, h)
        pixmap.fill(QColor("#1E2129")) # Match container background
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw mobile shape
        # Proportions: width 140, height 280
        phone_w, phone_h = 140, 280
        phone_x = (w - phone_w) // 2
        phone_y = (h - phone_h) // 2 - 20
        
        # Phone body
        pen = QPen(QColor("#8A92A6"))
        pen.setWidth(4)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(phone_x, phone_y, phone_w, phone_h, 15, 15)
        
        # Draw top speaker slot
        pen.setWidth(3)
        painter.setPen(pen)
        painter.drawLine(phone_x + phone_w//2 - 15, phone_y + 15, phone_x + phone_w//2 + 15, phone_y + 15)
        
        # Draw red dot
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#E53935")) # Red dot
        painter.drawEllipse(phone_x + phone_w//2 - 8, phone_y + 40, 16, 16)

        # Draw text "Device Inactive"
        painter.setPen(QColor("#8A92A6"))
        font = QFont("Inter", 18, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(0, phone_y + phone_h + 30, w, 40, Qt.AlignmentFlag.AlignCenter, "Device Inactive")
        
        painter.end()
        
        self.video_label.setPixmap(pixmap)

    def closeEvent(self, event):
        """Ensure thread stops cleanly on exit."""
        self.video_processor.stop()
        super().closeEvent(event)

    def apply_styles(self):
        """Apply custom CSS on top of qdarktheme."""
        self.setStyleSheet("""
            QWidget {
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            #Sidebar {
                background-color: #1A1C23;
                border-right: 1px solid #2D303E;
            }
            #ContentArea {
                background-color: #12141A;
            }
            QPushButton#SidebarBtn, QPushButton#SidebarBtnActive {
                text-align: left;
                padding: 12px 16px;
                border-radius: 8px;
                border: none;
                font-size: 14px;
                font-weight: 500;
                color: #A0A5B5;
                background-color: transparent;
            }
            QPushButton#SidebarBtn:hover {
                background-color: rgba(255, 255, 255, 0.05);
                color: #FFFFFF;
            }
            QPushButton#SidebarBtnActive {
                background-color: rgba(0, 229, 255, 0.1);
                color: #00E5FF;
                font-weight: bold;
                border-left: 3px solid #00E5FF;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
            }
            #VideoContainer {
                background-color: #1E2129;
                border-radius: 12px;
                border: 1px solid #2D303E;
            }
            #VideoLabel {
                color: #8A92A6;
                font-size: 16px;
            }
        """)

if __name__ == "__main__":
    # Get local IP for display
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()

    print("*" * 50)
    print(f"* Server running at: ws://{IP}:8000/ws/stream")
    print("*" * 50)

    # Start the uvicorn server in a background thread
    server_thread = threading.Thread(target=run_server, args=(IP,), daemon=True)
    server_thread.start()

    # Create and run the PyQt6 Dashboard
    qt_app = QApplication(sys.argv)
    
    # Apply global dark theme using qdarktheme
    qt_app.setStyleSheet(qdarktheme.load_stylesheet("dark"))

    dashboard = DashboardWindow(IP)
    dashboard.show()
    
    sys.exit(qt_app.exec())
