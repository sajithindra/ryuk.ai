import os
import sys
import cv2
import numpy as np
import time
from collections import deque

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QFrame, QStackedWidget,
    QLineEdit, QFileDialog, QMessageBox, QSpacerItem, 
    QSizePolicy, QApplication, QScrollArea, QGridLayout
)
from PyQt6.QtGui import QPixmap, QImage, QColor, QPainter, QPen, QFont, QBrush
from PyQt6.QtCore import Qt, QTimer

import core.watchdog_indexer as watchdog
from core.state import new_stream_signals
from components.video_worker import VideoProcessor

class CameraCard(QFrame):
    """A reusable UI card for a single camera stream."""
    def __init__(self, client_id, parent=None):
        super().__init__(parent)
        self.client_id = client_id
        self.setObjectName("VideoCard")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        
        # Header with ID
        self.lbl_id = QLabel(f"DEVICE ID: {client_id}")
        self.lbl_id.setStyleSheet("color: #00E5FF; font-family: 'Ubuntu Mono'; font-size: 11px; font-weight: bold; border: none;")
        
        # Main Video Label
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background: #000; border-radius: 6px; border: 1px solid #2D303E;")
        self.video_label.setMinimumSize(480, 360) # Increased base size for better mesh visibility
        
        self.layout.addWidget(self.lbl_id)
        self.layout.addWidget(self.video_label, 1)

class DashboardWindow(QMainWindow):
    def __init__(self, ip_address):
        super().__init__()
        self.ip_address = ip_address
        self.setWindowTitle("RYUK AI | God's Eye Dashboard")
        self.resize(1280, 850)
        
        # Track active processors and their UI cards: { client_id: {'worker': ..., 'card': ...} }
        self.active_sessions = {}
        self.selected_image_path = None
        
        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # ----------------- SIDEBAR -----------------
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(250)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(20, 40, 20, 20)
        
        title_label = QLabel("RYUK AI")
        title_label.setObjectName("SidebarTitle")
        
        subtitle_label = QLabel("GLOBAL SURVEILLANCE")
        subtitle_label.setStyleSheet("color: #8A92A6; font-size: 10px; font-weight: bold; letter-spacing: 1.5px;")

        self.btn_cameras = QPushButton("God's Eye Grid")
        self.btn_cameras.setObjectName("SidebarBtnActive")
        self.btn_cameras.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cameras.clicked.connect(lambda: self.switch_view(0))
        
        self.btn_watchdog = QPushButton("Watchdog Enrollment")
        self.btn_watchdog.setObjectName("SidebarBtn")
        self.btn_watchdog.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_watchdog.clicked.connect(lambda: self.switch_view(1))
        
        self.btn_reports = QPushButton("Central Intelligence")
        self.btn_reports.setObjectName("SidebarBtn")
        self.btn_reports.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.btn_settings = QPushButton("System Settings")
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
        sidebar_layout.addWidget(self.btn_watchdog)
        sidebar_layout.addWidget(self.btn_reports)
        sidebar_layout.addWidget(self.btn_settings)
        sidebar_layout.addStretch()
        sidebar_layout.addWidget(status_label)

        # ----------------- MAIN CONTENT (QStackedWidget) -----------------
        self.stacked_widget = QStackedWidget()
        
        # --- VIEW 0: Multi-Camera Grid ---
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setObjectName("ContentArea")
        self.grid_scroll.setStyleSheet("border: none;")
        
        self.grid_container = QWidget()
        self.grid_container.setStyleSheet("background-color: #0B0D0F;")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(30, 30, 30, 30)
        self.grid_layout.setSpacing(25)
        
        self.grid_scroll.setWidget(self.grid_container)
        
        # --- Empty State UI ---
        self.empty_label = QLabel("SYSTEM IDLE\nWaiting for active device streams...")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #2D303E; font-size: 24px; font-weight: bold; border: none;")
        self.grid_layout.addWidget(self.empty_label, 0, 0)
        
        # --- VIEW 1: Watchdog Enrollment ---
        self.wd_view = QFrame()
        self.wd_view.setObjectName("ContentArea")
        wd_layout = QVBoxLayout(self.wd_view)
        wd_layout.setContentsMargins(60, 60, 60, 60)
        
        wd_header = QLabel("Watchdog Enrollment")
        wd_header.setFont(QFont("Inter", 28, QFont.Weight.Bold))
        wd_header.setStyleSheet("color: #FFF; border: none;")
        
        form_frame = QFrame()
        form_frame.setStyleSheet("background-color: #16191E; border-radius: 16px; border: 1px solid #2D3139;")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(40,40,40,40)
        form_layout.setSpacing(15)
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Full Name")
        
        self.aadhar_input = QLineEdit()
        self.aadhar_input.setPlaceholderText("Aadhar Number (xxxx-xxxx-xxxx)")
        
        self.btn_browse = QPushButton("SELECT BIOMETRIC PHOTO...")
        self.btn_browse.setStyleSheet("padding: 15px; border: 2px dashed #2D3139; color: #8A92A6; border-radius: 8px; font-weight: bold;")
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse.clicked.connect(self.browse_image)
        
        self.img_path_label = QLabel("No photo selected...")
        self.img_path_label.setStyleSheet("color: #5C6370; font-size: 11px; border: none;")
        
        self.btn_submit_faiss = QPushButton("ENROLL IDENTITY")
        self.btn_submit_faiss.setStyleSheet("background-color: #4CAF50; color: #FFF; font-weight: bold; padding: 20px; border-radius: 12px; border: none;")
        self.btn_submit_faiss.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_submit_faiss.clicked.connect(self.submit_to_faiss)
        
        form_layout.addWidget(QLabel("IDENTITY DETAILS"))
        form_layout.addWidget(self.name_input)
        form_layout.addWidget(self.aadhar_input)
        form_layout.addSpacing(15)
        form_layout.addWidget(QLabel("FACIAL BIOMETRICS"))
        form_layout.addWidget(self.btn_browse)
        form_layout.addWidget(self.img_path_label)
        form_layout.addSpacing(25)
        form_layout.addWidget(self.btn_submit_faiss)
        
        wd_layout.addWidget(wd_header)
        wd_layout.addSpacing(30)
        wd_layout.addWidget(form_frame)
        wd_layout.addStretch()

        self.stacked_widget.addWidget(self.grid_scroll) # Index 0
        self.stacked_widget.addWidget(self.wd_view)    # Index 1
        
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.stacked_widget, 1)

        self.apply_styles()

        # Timer to poll for new streams
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.check_for_new_streams)
        self.poll_timer.start(500)

    def check_for_new_streams(self):
        """Checks global signal queue for new camera connections."""
        while len(new_stream_signals) > 0:
            client_id = new_stream_signals.popleft()
            if client_id not in self.active_sessions:
                self.start_new_stream_session(client_id)

    def start_new_stream_session(self, client_id):
        """Instantiates a new processor and grid card for a camera."""
        if not self.active_sessions:
            self.empty_label.hide()
            self.grid_layout.removeWidget(self.empty_label)

        # Create UI Card
        card = CameraCard(client_id)
        
        # Calculate grid position (2-column grid)
        count = len(self.active_sessions)
        row = count // 2
        col = count % 2
        self.grid_layout.addWidget(card, row, col)
        
        # Create Processor
        processor = VideoProcessor(client_id)
        # Connect signals with lambda to pass client_id context
        processor.frame_ready.connect(lambda qt_img, cid=client_id: self.update_stream_ui(cid, qt_img))
        processor.stream_inactive.connect(self.stop_stream_session)
        
        self.active_sessions[client_id] = {
            'worker': processor,
            'card': card
        }
        processor.start()
        print(f"UI: Active Session started for source {client_id}")

    def update_stream_ui(self, client_id, qt_img):
        """Updates a specific card's video label."""
        if client_id in self.active_sessions:
            session = self.active_sessions[client_id]
            label = session['card'].video_label
            label.setPixmap(QPixmap.fromImage(qt_img))
            # Dynamic size feedback for optimization
            session['worker'].set_target_size(label.width(), label.height())

    def stop_stream_session(self, client_id):
        """Removes a camera card and stops the processor."""
        if client_id in self.active_sessions:
            print(f"UI: Terminating session for source {client_id}")
            session = self.active_sessions.pop(client_id)
            session['worker'].stop()
            session['card'].deleteLater()
            
            # Show empty state if none left
            if not self.active_sessions:
                self.grid_layout.addWidget(self.empty_label, 0, 0)
                self.empty_label.show()

    def switch_view(self, index):
        self.stacked_widget.setCurrentIndex(index)
        buttons = [self.btn_cameras, self.btn_watchdog]
        for idx, btn in enumerate(buttons):
            btn.setObjectName("SidebarBtnActive" if idx == index else "SidebarBtn")
        self.sidebar.setStyleSheet(self.sidebar.styleSheet())

    def browse_image(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Face Identity", "", "Image Files (*.png *.jpg *.jpeg)")
        if file_name:
            self.selected_image_path = file_name
            self.img_path_label.setText(file_name)

    def submit_to_faiss(self):
        aadhar = self.aadhar_input.text().strip()
        name = self.name_input.text().strip()
        
        if not name or not aadhar or not self.selected_image_path:
            QMessageBox.warning(self, "Input Error", "Please fill all fields and select a photo.")
            return
            
        self.btn_submit_faiss.setText("ENROLLING NOURAL DATA...")
        self.btn_submit_faiss.setDisabled(True)
        QApplication.processEvents()
        
        try:
            watchdog.enroll_face(self.selected_image_path, aadhar, name)
            QMessageBox.information(self, "Ryuk AI", f"Success: {name} is now globally recognized.")
            self.name_input.clear()
            self.aadhar_input.clear()
            self.selected_image_path = None
            self.img_path_label.setText("No photo selected...")
            
        except Exception as e:
            QMessageBox.critical(self, "Enrollment Error", str(e))
        finally:
            self.btn_submit_faiss.setText("ENROLL IDENTITY")
            self.btn_submit_faiss.setDisabled(False)

    def closeEvent(self, event):
        for session in self.active_sessions.values():
            session['worker'].stop()
        super().closeEvent(event)

    def apply_styles(self):
        self.setStyleSheet("""
            QWidget {
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            #Sidebar {
                background-color: #111318;
                border-right: 1px solid #2D3139;
            }
            #SidebarTitle {
                color: #00E5FF;
                font-size: 24px;
                font-weight: 800;
                margin-bottom: 2px;
            }
            #SidebarBtn, #SidebarBtnActive {
                text-align: left;
                padding: 12px 18px;
                border-radius: 8px;
                font-size: 13px;
                font-weight: 600;
                border: none;
                margin-top: 4px;
            }
            #SidebarBtn {
                color: #8A92A6;
                background: transparent;
            }
            #SidebarBtn:hover {
                background-color: rgba(255, 255, 255, 0.05);
                color: #FFFFFF;
            }
            #SidebarBtnActive {
                color: #FFFFFF;
                background-color: #2D303E;
                border: 1px solid #3E4253;
            }
            #ContentArea {
                background-color: #0B0D0F;
            }
            #VideoCard {
                background-color: #16191E;
                border: 1px solid #2D3139;
                border-radius: 12px;
            }
            QLineEdit {
                background-color: #0B0D0F;
                border: 1px solid #2D3139;
                border-radius: 8px;
                padding: 12px;
                color: #FFFFFF;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #00E5FF;
            }
            QLabel {
                color: #FFF;
            }
        """)
