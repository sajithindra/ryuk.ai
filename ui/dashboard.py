import os
import sys
import cv2
import numpy as np
import time
import base64
import json
import threading
from collections import deque
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QFrame, QStackedWidget,
    QLineEdit, QFileDialog, QMessageBox, QSpacerItem, 
    QSizePolicy, QApplication, QScrollArea, QGridLayout,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QGraphicsDropShadowEffect
)
from PyQt6.QtGui import QPixmap, QImage, QColor, QPainter, QPen, QFont, QBrush, QIcon, QTextDocument, QPageLayout
from PyQt6.QtCore import Qt, QTimer, QSize, QPropertyAnimation, QEasingCurve, pyqtSignal, QByteArray, QThread, QMarginsF
from PyQt6.QtPrintSupport import QPrinter

import core.watchdog_indexer as watchdog
from core.state import new_stream_signals, cache, global_signals
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
        self.video_label.setStyleSheet("background: rgba(0, 0, 0, 0.3); border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.08);")
        self.video_label.setMinimumSize(480, 360) # Increased base size for better mesh visibility
        
        self.layout.addWidget(self.lbl_id)
        self.layout.addWidget(self.video_label, 1)

class SystemHealthIndicator(QFrame):
    """A compact utility bar showing server and database connectivity status."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setStyleSheet("background: rgba(255, 255, 255, 0.02); border-top: 1px solid rgba(255, 255, 255, 0.05);")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 15, 0)
        
        self.lbl_redis = QLabel("REDIS: CONNECTED")
        self.lbl_redis.setStyleSheet("color: #00E5FF; font-size: 9px; font-weight: bold; border: none;")
        
        self.lbl_mongo = QLabel("MONGO: CONNECTED")
        self.lbl_mongo.setStyleSheet("color: #00E5FF; font-size: 9px; font-weight: bold; border: none;")
        
        layout.addWidget(self.lbl_redis)
        layout.addSpacing(20)
        layout.addWidget(self.lbl_mongo)
        layout.addStretch()

    def update_status(self, redis_ok, mongo_ok):
        self.lbl_redis.setText(f"REDIS: {'CONNECTED' if redis_ok else 'DISCONNECTED'}")
        self.lbl_redis.setStyleSheet(f"color: {'#00E5FF' if redis_ok else '#FF1744'}; font-size: 9px; font-weight: bold; border: none;")
        self.lbl_mongo.setText(f"MONGO: {'CONNECTED' if mongo_ok else 'DISCONNECTED'}")
        self.lbl_mongo.setStyleSheet(f"color: {'#00E5FF' if mongo_ok else '#FF1744'}; font-size: 9px; font-weight: bold; border: none;")

class PersonInfoCard(QFrame):
    """A premium intelligence blade for high-fidelity situational awareness."""
    def __init__(self, meta, parent=None):
        super().__init__(parent)
        threat = meta.get('threat_level', 'Low')
        threat_color = "#FF1744" if threat == "High" else "#00E676"
        
        self.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(11, 13, 15, 0.98);
                border: 1px solid #2D3139;
                border-left: 4px solid {threat_color};
                border-radius: 4px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # --- BLADE HEADER ---
        header = QHBoxLayout()
        
        # Photo Thumbnail
        self.photo_lbl = QLabel()
        self.photo_lbl.setFixedSize(50, 50)
        self.photo_lbl.setStyleSheet(f"border: 2px solid {threat_color}; border-radius: 25px; background: #000;")
        thumb_b64 = meta.get('photo_thumb', '')
        if thumb_b64:
            try:
                img_data = base64.b64decode(thumb_b64)
                pixmap = QPixmap()
                pixmap.loadFromData(img_data)
                self.photo_lbl.setPixmap(pixmap.scaled(50, 50, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
                self.photo_lbl.setMask(QPixmap(50, 50)) # Simple circle mask placeholder if needed, usually border-radius handles it in CSS for QFrame but QLabel might need more.
            except: pass
        
        name_layout = QVBoxLayout()
        name = meta.get('name', 'Unknown Target').upper()
        lbl_name = QLabel(name)
        lbl_name.setStyleSheet(f"color: #FFFFFF; font-weight: 900; font-size: 16px; border: none; background: transparent;")
        
        lbl_subtitle = QLabel("BIOMETRIC IDENTIFIED")
        lbl_subtitle.setStyleSheet("color: #8A92A6; font-size: 9px; font-weight: 800; letter-spacing: 1px; border: none; background: transparent;")
        
        name_layout.addWidget(lbl_subtitle)
        name_layout.addWidget(lbl_name)
        
        header.addWidget(self.photo_lbl)
        header.addSpacing(10)
        header.addLayout(name_layout)
        header.addStretch()
        
        # Threat Badge
        badge = QLabel(threat.upper())
        badge.setFixedWidth(70)
        badge.setFixedHeight(22)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"""
            background-color: {threat_color}22;
            color: {threat_color};
            border: 1px solid {threat_color};
            border-radius: 4px;
            font-size: 10px;
            font-weight: 900;
        """)
        header.addWidget(badge)
        layout.addLayout(header)
        
        # --- SEPARATOR ---
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #1A1D23; border: none;")
        layout.addWidget(sep)
        
        # --- ATTRIBUTE LIST ---
        def add_attribute(label, value, is_mono=False):
            container = QWidget()
            container.setStyleSheet("background: transparent; border: none;")
            h_lay = QHBoxLayout(container)
            h_lay.setContentsMargins(0, 0, 0, 0)
            
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #5C6370; font-weight: 800; font-size: 10px; border: none;")
            lbl.setFixedWidth(60)
            
            val = QLabel(str(value))
            font_style = "font-family: 'Ubuntu Mono'; " if is_mono else ""
            val.setStyleSheet(f"color: #E2E8F0; {font_style} font-size: 12px; border: none;")
            val.setWordWrap(True)
            
            h_lay.addWidget(lbl)
            h_lay.addWidget(val, 1)
            layout.addWidget(container)

        add_attribute("UID", meta.get('aadhar', 'N/A'), is_mono=True)
        add_attribute("MOBILE", meta.get('phone', 'N/A'), is_mono=True)
        add_attribute("LOC", meta.get('address', 'N/A'))
        
        # Bottom Margin
        layout.addSpacing(4)

from PyQt6.QtWidgets import QTextEdit

class DossierWorker(QThread):
    progress_update = pyqtSignal(str)
    chunk_received = pyqtSignal(str)
    finished_generation = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, meta, timeframe_label):
        super().__init__()
        self.meta = meta
        self.timeframe_label = timeframe_label

    def run(self):
        try:
            self.progress_update.emit("> Booting Ryuk Intelligence Core...")
            self.msleep(600)
            
            self.progress_update.emit(f"> Requesting raw telemetry from MongoDB for timeframe: {self.timeframe_label}...")
            
            days_ago = None
            if self.timeframe_label == "Today":
                days_ago = 1
            elif self.timeframe_label == "Last 7 Days":
                days_ago = 7
                
            from core.watchdog_indexer import get_activity_report
            logs = get_activity_report(self.meta['aadhar'], limit=150, days_ago=days_ago)
            
            self.progress_update.emit(f"> Extracted {len(logs)} MongoDB records.")
            self.msleep(400)
            
            self.progress_update.emit("> Transmitting raw intelligence to Gemini 1.5 Pro...")
            self.msleep(800)
            
            from core.agent import ryuk_agent
            
            # Start streaming the response
            self.progress_update.emit("STREAM_START")
            for chunk in ryuk_agent.generate_dossier_stream(self.meta, logs, self.timeframe_label):
                self.chunk_received.emit(chunk)
                
            self.finished_generation.emit()
            
        except Exception as e:
            self.error_occurred.emit(str(e))

class ActivityReportDialog(QMainWindow):
    """A visual chronological timeline & AI Reporting suite for tracking target movements."""
    def __init__(self, meta, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setWindowTitle(f"TACTICAL INTELLIGENCE | {meta.get('name', 'Unknown').upper()}")
        self.setFixedSize(900, 700)
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1b26, stop:1 #0f1015);
                color: white;
            }
            QWidget {
                font-family: '-apple-system', 'Segoe UI', 'SF Pro Display', sans-serif;
            }
        """)
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # Left Column: Raw Logs
        left_col = QVBoxLayout()
        header = QLabel("CHRONOLOGICAL LOGS")
        header.setStyleSheet("color: #00E5FF; font-weight: 800; font-size: 14px; margin-bottom: 10px;")
        left_col.addWidget(header)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedWidth(350)
        self.scroll.setStyleSheet("border: none; background: transparent;")
        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.container)
        left_col.addWidget(self.scroll)
        
        # Right Column: AI Analysis
        right_col = QVBoxLayout()
        
        ai_header_lay = QHBoxLayout()
        ai_header = QLabel("AI TACTICAL DOSSIER")
        ai_header.setStyleSheet("color: #00E5FF; font-weight: 800; font-size: 14px;")
        ai_header_lay.addWidget(ai_header)
        
        self.timeframe_cb = QComboBox()
        self.timeframe_cb.addItems(["All Time", "Today", "Last 7 Days"])
        self.timeframe_cb.setStyleSheet("background-color: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 6px; color: #FFF; font-weight: 500;")
        ai_header_lay.addWidget(self.timeframe_cb)
        
        right_col.addLayout(ai_header_lay)
        
        self.btn_generate = QPushButton("GENERATE DOSSIER")
        self.btn_generate.setStyleSheet("background-color: rgba(0, 229, 255, 0.15); color: #00E5FF; font-weight: bold; padding: 12px; border-radius: 12px; border: 1px solid rgba(0, 229, 255, 0.3);")
        self.btn_generate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_generate.clicked.connect(self.generate_report)
        
        self.btn_download = QPushButton("DOWNLOAD PDF")
        self.btn_download.setStyleSheet("background-color: rgba(0, 230, 118, 0.15); color: #00E676; font-weight: bold; padding: 12px; border-radius: 12px; border: 1px solid rgba(0, 230, 118, 0.3);")
        self.btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_download.clicked.connect(self.download_pdf)
        self.btn_download.hide() # Hidden until report exists
        
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.btn_generate)
        btn_layout.addWidget(self.btn_download)
        
        right_col.addLayout(btn_layout)
        
        self.report_view = QTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setStyleSheet("background-color: rgba(0, 0, 0, 0.2); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 15px; color: #E0E0E0; font-size: 13px; line-height: 1.4;")
        self.report_view.setPlaceholderText("Awaiting command. Select a timeframe and generate the intelligence dossier.")
        right_col.addWidget(self.report_view)
        
        main_layout.addLayout(left_col)
        main_layout.addLayout(right_col, 1) # Right gets more space
        
        self.logs = []
        self.load_report()

    def load_report(self):
        self.logs = watchdog.get_activity_report(self.meta['aadhar'])
        if not self.logs:
            lbl = QLabel("No activity recorded for this profile.")
            lbl.setStyleSheet("color: #8A92A6; font-size: 12px; font-style: italic;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_layout.addWidget(lbl)
            return

        for log in self.logs:
            row = QFrame()
            # Removed borders and background styling 
            row.setStyleSheet("background-color: transparent; border: none; margin-bottom: 5px;")
            r_lay = QVBoxLayout(row)
            r_lay.setContentsMargins(0, 0, 0, 0)
            r_lay.setSpacing(2)
            
            time_str = log.get('date_str', 'Unknown Time')
            locs = log.get('locations', ["Unknown", "Unknown"])
            cam_str = log.get('client_id', 'Unknown Device')
            
            time_lbl = QLabel(time_str)
            time_lbl.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 11px;")
            
            loc_lbl = QLabel(f"📍 {locs[0]} ➔ {locs[1]}")
            loc_lbl.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: 600;")
            
            cam_lbl = QLabel(f"DEVICE ID: {cam_str}")
            cam_lbl.setStyleSheet("color: #8A92A6; font-size: 10px; font-family: 'Ubuntu Mono';")
            
            r_lay.addWidget(time_lbl)
            r_lay.addWidget(loc_lbl)
            r_lay.addWidget(cam_lbl)
            
            self.list_layout.addWidget(row)

    def generate_report(self):
        self.btn_generate.setText("SYNTHESIZING INTELLIGENCE...")
        self.btn_generate.setDisabled(True)
        self.report_view.setPlainText("Ryuk Terminal initialized.\n")
        
        tf_label = self.timeframe_cb.currentText()
        
        # We need to attach self.worker to ActivityReportDialog so they are available
        self.worker = DossierWorker(self.meta, tf_label)
        self.worker.progress_update.connect(self.on_progress)
        self.worker.chunk_received.connect(self.on_chunk)
        self.worker.finished_generation.connect(self.on_finished)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.start()
        
    def on_progress(self, msg):
        if msg == "STREAM_START":
            self.report_view.clear()
            self.current_dossier = ""
        else:
            self.report_view.append(msg)
            
    def on_chunk(self, chunk):
        self.current_dossier += chunk
        self.report_view.setMarkdown(self.current_dossier)
        
    def on_finished(self):
        self.btn_generate.setText("GENERATE DOSSIER")
        self.btn_generate.setDisabled(False)
        self.btn_download.show()
        
    def on_error(self, error):
        self.report_view.append(f"\n[!] ERROR: {error}")
        self.btn_generate.setText("GENERATE DOSSIER")
        self.btn_generate.setDisabled(False)
        self.btn_download.hide()
        
    def download_pdf(self):
        """Renders the current markdown dossier out to a PDF file."""
        import os
        from datetime import datetime
        name_safestr = self.meta.get('name', 'unknown').lower().replace(' ', '_')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"ryuk_dossier_{name_safestr}_{timestamp}.pdf"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Save Intelligence Dossier", 
            os.path.join(os.path.expanduser("~"), "Downloads", default_filename),
            "PDF Files (*.pdf)"
        )
        
        if file_path:
            try:
                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                printer.setOutputFileName(file_path)
                printer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
                
                # The easiest way to print is to let the QTextEdit paint to the printer
                self.report_view.document().print(printer)
                
                QMessageBox.information(self, "Export Complete", f"Dossier successfully saved to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", f"Failed to generate PDF:\n{str(e)}")

class EditProfileDialog(QMainWindow):
    """A sleek overlay to edit existing person intelligence."""
    def __init__(self, meta, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setWindowTitle("EDIT BIOMETRIC PROFILE")
        self.setFixedSize(400, 600)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1b26, stop:1 #0f1015);
                color: white;
            }
            QWidget {
                font-family: '-apple-system', 'Segoe UI', 'SF Pro Display', sans-serif;
            }
        """)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        
        header = QLabel("UPDATE PROFILE")
        header.setStyleSheet("color: #00E5FF; font-weight: 800; font-size: 18px; margin-bottom: 5px;")
        layout.addWidget(header)
        
        # Photo Display
        self.photo_lbl = QLabel()
        self.photo_lbl.setFixedSize(100, 100)
        self.photo_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.photo_lbl.setStyleSheet("border-radius: 50px; background: #16191E; border: 2px solid #2D3139;")
        self.photo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_b64 = meta.get('photo_thumb', '')
        if thumb_b64:
            try:
                data = base64.b64decode(thumb_b64)
                pixmap = QPixmap()
                pixmap.loadFromData(data)
                self.photo_lbl.setPixmap(pixmap.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
                # Circular mask for photo
                mask = QPixmap(100, 100)
                mask.fill(Qt.GlobalColor.transparent)
                p = QPainter(mask)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setBrush(QBrush(Qt.GlobalColor.black))
                p.drawEllipse(0, 0, 100, 100)
                p.end()
                self.photo_lbl.setMask(mask.mask())
            except: pass
        layout.addWidget(self.photo_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        
        self.name_in = QLineEdit(meta.get('name', ''))
        self.name_in.setPlaceholderText("Name")
        
        self.phone_in = QLineEdit(meta.get('phone', ''))
        self.phone_in.setPlaceholderText("Phone")
        
        self.address_in = QLineEdit(meta.get('address', ''))
        self.address_in.setPlaceholderText("Address")
        
        self.threat_in = QComboBox()
        self.threat_in.addItems(["Low", "Medium", "High"])
        self.threat_in.setCurrentText(meta.get('threat_level', 'Low'))
        self.threat_in.setStyleSheet("background-color: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 12px; color: #FFFFFF;")
        
        layout.addWidget(QLabel("FULL NAME"))
        layout.addWidget(self.name_in)
        layout.addWidget(QLabel("PHONE"))
        layout.addWidget(self.phone_in)
        layout.addWidget(QLabel("RESIDENCE"))
        layout.addWidget(self.address_in)
        layout.addWidget(QLabel("SECURITY CLEARANCE"))
        layout.addWidget(self.threat_in)
        
        layout.addStretch()
        
        btn_save = QPushButton("SAVE CHANGES")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet("background-color: #00E5FF; color: #000; font-weight: bold; padding: 15px; border-radius: 8px; border: none;")
        btn_save.clicked.connect(self.save)
        layout.addWidget(btn_save)

    def save(self, checked=False):
        data = {
            "name": self.name_in.text(),
            "phone": self.phone_in.text(),
            "address": self.address_in.text(),
            "threat_level": self.threat_in.currentText()
        }
        watchdog.update_profile(self.meta['aadhar'], data)
        self.close()

class ProfileRow(QFrame):
    """A premium management row for the Central Intelligence list with facial thumbnails."""
    def __init__(self, meta, on_edit, on_history, on_delete, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
            }
            QFrame:hover {
                background-color: rgba(255, 255, 255, 0.08);
                border-color: rgba(255, 255, 255, 0.2);
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(15)
        
        # Thumbnail
        self.thumb = QLabel()
        self.thumb.setFixedSize(40, 40)
        self.thumb.setStyleSheet("border-radius: 20px; background: #000; border: 1px solid #2D3139;")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_b64 = meta.get('photo_thumb', '')
        if thumb_b64:
            try:
                data = base64.b64decode(thumb_b64)
                pixmap = QPixmap()
                pixmap.loadFromData(data)
                self.thumb.setPixmap(pixmap.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
            except: pass
        
        info_layout = QVBoxLayout()
        name_lbl = QLabel(meta.get('name', 'Unknown').upper())
        name_lbl.setStyleSheet("color: #FFFFFF; font-weight: 800; font-size: 13px; border: none; background: transparent;")
        meta_lbl = QLabel(f"UID: {meta.get('aadhar')} | TEL: {meta.get('phone')}")
        meta_lbl.setStyleSheet("color: #8A92A6; font-family: 'Ubuntu Mono'; font-size: 10px; border: none; background: transparent;")
        info_layout.addWidget(name_lbl)
        info_layout.addWidget(meta_lbl)
        
        threat = meta.get('threat_level', 'Low')
        threat_color = "#FF1744" if threat == "High" else "#00E676"
        threat_badge = QLabel(threat.upper())
        threat_badge.setFixedWidth(70)
        threat_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        threat_badge.setStyleSheet(f"""
            color: {threat_color}; 
            background: transparent;
            border: none;
            font-size: 11px; 
            font-weight: 900; 
        """)
        
        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        btn_edit = QPushButton("EDIT")
        btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_edit.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.05); color: white; border-radius: 6px; padding: 6px 12px; font-size: 11px; font-weight: bold; border: 1px solid rgba(255, 255, 255, 0.1);
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.15);
            }
        """)
        btn_edit.clicked.connect(on_edit)

        btn_history = QPushButton("HISTORY")
        btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_history.setStyleSheet("""
            QPushButton {
                background: rgba(0, 229, 255, 0.1); color: #00E5FF; border: 1px solid rgba(0, 229, 255, 0.3); border-radius: 6px; padding: 6px 12px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(0, 229, 255, 0.2);
            }
        """)
        btn_history.clicked.connect(on_history)
        
        btn_delete = QPushButton("PURGE")
        btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_delete.setStyleSheet("""
            QPushButton {
                background: rgba(255, 23, 68, 0.1); color: #FF1744; border: 1px solid rgba(255, 23, 68, 0.3); border-radius: 6px; padding: 6px 12px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255, 23, 68, 0.2);
            }
        """)
        btn_delete.clicked.connect(on_delete)
        
        layout.addWidget(self.thumb)
        layout.addLayout(info_layout, 1)
        layout.addWidget(threat_badge)
        layout.addSpacing(10)
        layout.addWidget(btn_edit)
        layout.addWidget(btn_history)
        layout.addWidget(btn_delete)

class DashboardWindow(QMainWindow):
    def __init__(self, ip_address):
        super().__init__()
        self.ip_address = ip_address
        self.setWindowTitle("RYUK AI | God's Eye Dashboard")
        self.resize(1280, 850)
        
        # Track active processors and their UI cards: { client_id: {'worker': ..., 'card': ...} }
        self.active_sessions = {}
        self.selected_image_path = None
        
        # Security Alert PubSub
        self.pubsub = cache.pubsub(ignore_subscribe_messages=True)
        self.pubsub.subscribe("security_alerts")
        
        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.root_layout = QVBoxLayout(central_widget)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        # ----------------- ALERT BANNER (HIDDEN) -----------------
        self.alert_banner = QFrame()
        self.alert_banner.setFixedHeight(60)
        self.alert_banner.setStyleSheet("background: #FF1744; border-bottom: 2px solid #D50000;")
        self.alert_banner.hide()
        alert_layout = QHBoxLayout(self.alert_banner)
        self.alert_label = QLabel("SECURITY ALERT!")
        self.alert_label.setStyleSheet("color: white; font-weight: bold; font-size: 16px;")
        btn_close_alert = QPushButton("DISMISS")
        btn_close_alert.setFixedWidth(100)
        btn_close_alert.clicked.connect(self.alert_banner.hide)
        alert_layout.addSpacing(20)
        alert_layout.addWidget(self.alert_label)
        alert_layout.addStretch()
        alert_layout.addWidget(btn_close_alert)
        alert_layout.addSpacing(20)

        self.root_layout.addWidget(self.alert_banner)

        main_layout = QHBoxLayout()
        self.root_layout.addLayout(main_layout, 1)
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
        self.btn_reports.clicked.connect(lambda: self.switch_view(2))
        
        self.btn_settings = QPushButton("System Settings")
        self.btn_settings.setObjectName("SidebarBtn")
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(lambda: self.switch_view(3))

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
        
        # System Health Indicator for Heartbeat Hub
        self.health_indicator = SystemHealthIndicator()
        sidebar_layout.addWidget(self.health_indicator)

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
        
        wd_header = QLabel("WATCHDOG ENROLLMENT")
        wd_header.setStyleSheet("color: #FFFFFF; font-size: 24px; font-weight: 800;")
        
        form_frame = QFrame()
        form_frame.setStyleSheet("background-color: #16191E; border-radius: 16px; border: 1px solid #2D3139;")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(40,40,40,40)
        form_layout.setSpacing(15)
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Full Name")
        
        self.aadhar_input = QLineEdit()
        self.aadhar_input.setPlaceholderText("Aadhar Number (xxxx-xxxx-xxxx)")
        
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Phone Number (+91-xxxx-xxxxxx)")
        
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("Residence Address")
        
        self.threat_input = QComboBox()
        self.threat_in_items = ["Low", "Medium", "High"]
        self.threat_input.addItems(self.threat_in_items)
        self.threat_input.setStyleSheet("background-color: #0B0D0F; border: 1px solid #2D3139; border-radius: 8px; padding: 12px; color: #FFFFFF;")
        
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
        form_layout.addWidget(self.phone_input)
        form_layout.addWidget(self.address_input)
        form_layout.addWidget(QLabel("THREAT CLASSIFICATION"))
        form_layout.addWidget(self.threat_input)
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

        # --- VIEW 2: Central Intelligence (Management) ---
        self.ci_view = QFrame()
        self.ci_view.setObjectName("ContentArea")
        ci_layout = QVBoxLayout(self.ci_view)
        ci_layout.setContentsMargins(60, 60, 60, 60)
        
        ci_header = QLabel("CENTRAL INTELLIGENCE")
        ci_header.setStyleSheet("color: #FFFFFF; font-size: 24px; font-weight: 800;")
        
        # Search Bar
        self.ci_search = QLineEdit()
        self.ci_search.setPlaceholderText("Search Registry (Name or UID)...")
        self.ci_search.textChanged.connect(self.filter_ci_list)
        
        # List Container
        self.ci_scroll = QScrollArea()
        self.ci_scroll.setWidgetResizable(True)
        self.ci_scroll.setStyleSheet("border: none; background: transparent;")
        self.ci_list_container = QWidget()
        self.ci_list_layout = QVBoxLayout(self.ci_list_container)
        self.ci_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.ci_list_layout.setSpacing(10)
        self.ci_scroll.setWidget(self.ci_list_container)
        
        ci_layout.addWidget(ci_header)
        ci_layout.addSpacing(20)
        ci_layout.addWidget(self.ci_search)
        ci_layout.addSpacing(10)
        ci_layout.addWidget(self.ci_scroll)

        self.stacked_widget.addWidget(self.grid_scroll) # Index 0
        self.stacked_widget.addWidget(self.wd_view)    # Index 1
        self.stacked_widget.addWidget(self.ci_view)    # Index 2
        
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.stacked_widget, 1)

        # ----------------- INTELLIGENCE PANEL (RIGHT) -----------------
        self.intel_panel = QFrame()
        self.intel_panel.setFixedWidth(0) # Start hidden
        self.intel_panel.setStyleSheet("background-color: rgba(20, 22, 30, 0.7); border-left: 1px solid rgba(255, 255, 255, 0.08);")
        intel_layout = QVBoxLayout(self.intel_panel)
        intel_layout.setContentsMargins(0, 0, 0, 0)
        
        intel_header = QLabel("DETECTED INTEL")
        intel_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        intel_header.setStyleSheet("color: #00E5FF; font-weight: 800; font-size: 13px; padding: 25px; border-bottom: 1px solid #2D3139;")
        intel_layout.addWidget(intel_header)
        
        self.intel_scroll = QScrollArea()
        self.intel_scroll.setWidgetResizable(True)
        self.intel_scroll.setStyleSheet("border: none; background: transparent;")
        self.intel_container = QWidget()
        self.intel_container.setStyleSheet("background: transparent;")
        self.intel_list_layout = QVBoxLayout(self.intel_container)
        self.intel_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.intel_list_layout.setSpacing(15)
        self.intel_list_layout.setContentsMargins(15, 20, 15, 20)
        self.intel_scroll.setWidget(self.intel_container)
        
        intel_layout.addWidget(self.intel_scroll)
        
        main_layout.addWidget(self.intel_panel)
        
        # Sliding Animation
        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
        self.intel_animation = QPropertyAnimation(self.intel_panel, b"maximumWidth")
        self.intel_animation.setDuration(300)
        self.intel_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        self.intel_min_anim = QPropertyAnimation(self.intel_panel, b"minimumWidth")
        self.intel_min_anim.setDuration(300)
        self.intel_min_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # Track active info cards: {aadhar: card_widget}
        self.active_intel_cards = {}
        # Track last detection time for auto-cleanup
        self.intel_last_seen = {}

        self.apply_styles()

        # Timer to poll for new streams
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.check_for_new_streams)
        self.poll_timer.start(500)

        # Timer to poll for security alerts
        self.alert_timer = QTimer()
        self.alert_timer.timeout.connect(self.check_for_alerts)
        self.alert_timer.start(200)

        # Timer for Sidebar Cleanup
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self.cleanup_sidebar)
        self.cleanup_timer.start(1000)
        
        # System Health Heartbeat
        self.health_timer = QTimer()
        self.health_timer.timeout.connect(self.check_system_health)
        self.health_timer.start(3000)

    def toggle_intel_panel(self, show):
        target_width = 320 if show else 0
        self.intel_animation.stop()
        self.intel_min_anim.stop()
        self.intel_animation.setEndValue(target_width)
        self.intel_min_anim.setEndValue(target_width)
        self.intel_animation.start()
        self.intel_min_anim.start()

    def check_system_health(self):
        """Monitors connectivity to Redis and MongoDB services."""
        redis_ok = False
        mongo_ok = False
        try:
            cache.ping()
            redis_ok = True
        except: pass
        
        try:
            # Quick ping for MongoDB (sync)
            from core.database import get_sync_db
            db_sync = get_sync_db()
            db_sync.command('ping')
            mongo_ok = True
        except: pass
        
        self.health_indicator.update_status(redis_ok, mongo_ok)

    def cleanup_sidebar(self):
        """Removes intelligence cards for people who haven't been seen recently."""
        now = time.time()
        to_remove = []
        for aadhar, last_seen in self.intel_last_seen.items():
            if now - last_seen > 5.0:
                to_remove.append(aadhar)
        
        for aadhar in to_remove:
            if aadhar in self.active_intel_cards:
                card = self.active_intel_cards.pop(aadhar)
                self.intel_list_layout.removeWidget(card)
                card.deleteLater()
                del self.intel_last_seen[aadhar]
        
        if not self.active_intel_cards and self.intel_panel.width() > 0:
            self.toggle_intel_panel(False)

    def handle_detection(self, metadata):
        """Processes an identification signal and updates the sidebar."""
        aadhar = metadata.get('aadhar')
        if not aadhar: return
        
        self.intel_last_seen[aadhar] = time.time()
        
        if aadhar not in self.active_intel_cards:
            if not self.active_intel_cards:
                self.toggle_intel_panel(True)
            card = PersonInfoCard(metadata)
            self.active_intel_cards[aadhar] = card
            self.intel_list_layout.insertWidget(0, card)

    def check_for_alerts(self):
        """Checks Redis for high-security alert messages."""
        msg = self.pubsub.get_message()
        if msg:
            try:
                alert = json.loads(msg['data'].decode('utf-8'))
                if alert.get("type") == "SECURITY_ALERT":
                    self.alert_label.setText(alert['message'])
                    self.alert_banner.show()
            except Exception:
                pass

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
        # Connect signals
        processor.frame_ready.connect(lambda qt_img, cid=client_id: self.update_stream_ui(cid, qt_img))
        processor.stream_inactive.connect(self.stop_stream_session)
        processor.person_identified.connect(self.handle_detection)
        
        self.active_sessions[client_id] = {
            'worker': processor,
            'card': card
        }
        
        # Register camera metadata if not exists
        watchdog.register_camera_metadata(client_id, ["Airport", "Railway Station"])
        
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
        # Contextual Visibility: Only show intelligence panel in God's Eye Grid (index 0)
        if index != 0:
            if hasattr(self, 'intel_panel') and self.intel_panel.width() > 0:
                self.toggle_intel_panel(False)
        else:
            # Re-show if there are active detections when switching BACK to God's Eye
            if hasattr(self, 'active_intel_cards') and self.active_intel_cards:
                self.toggle_intel_panel(True)

        # Update button styles
        btns = [self.btn_cameras, self.btn_watchdog, self.btn_reports, self.btn_settings]
        for i, btn in enumerate(btns):
            btn.setObjectName("SidebarBtnActive" if i == index else "SidebarBtn")
        self.apply_styles()
        
        if index == 2:
            self.load_central_intelligence()

    def load_central_intelligence(self):
        """Fetches and displays all targets in the global registry."""
        # Clear existing
        while self.ci_list_layout.count():
            item = self.ci_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        profiles = watchdog.get_all_profiles()
        for p in profiles:
            row = ProfileRow(
                p, 
                on_edit=lambda checked=False, meta=p: self.handle_edit_profile(meta),
                on_history=lambda checked=False, meta=p: self.handle_view_history(meta),
                on_delete=lambda checked=False, uid=p['aadhar']: self.handle_delete_profile(uid)
            )
            self.ci_list_layout.addWidget(row)
            
    def filter_ci_list(self):
        """Dynamic search for the target registry."""
        query = self.ci_search.text().lower().strip()
        for i in range(self.ci_list_layout.count()):
            widget = self.ci_list_layout.itemAt(i).widget()
            if widget:
                match = (query in widget.meta.get('name', '').lower() or 
                         query in widget.meta.get('aadhar', '').lower())
                widget.setVisible(match)

    def handle_view_history(self, meta):
        """Displays a chronological activity report for a profile."""
        self.history_dialog = ActivityReportDialog(meta, self)
        self.history_dialog.show()

    def handle_edit_profile(self, meta):
        """Launches the biometric edit suite."""
        self.edit_dialog = EditProfileDialog(meta, self)
        # We want to refresh list after dialog close
        self.edit_dialog.destroyed.connect(self.load_central_intelligence)
        self.edit_dialog.show()

    def handle_delete_profile(self, aadhar):
        """Removes a target from global recognition."""
        reply = QMessageBox.question(self, "Security Clearance", 
                                   f"Are you sure you want to permanently delete profile {aadhar}?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            watchdog.delete_profile(aadhar)
            self.load_central_intelligence()
            QMessageBox.information(self, "Ryuk AI", "Target profile purged from central registry.")


    def browse_image(self, checked=False):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Face Identity", "", "Image Files (*.png *.jpg *.jpeg)")
        if file_name:
            self.selected_image_path = file_name
            self.img_path_label.setText(file_name)

    def submit_to_faiss(self, checked=False):
        aadhar = self.aadhar_input.text().strip()
        name = self.name_input.text().strip()
        phone = self.phone_input.text().strip()
        address = self.address_input.text().strip()
        threat = self.threat_input.currentText()
        
        if not name or not aadhar or not self.selected_image_path:
            QMessageBox.warning(self, "Input Error", "Please fill name, aadhar, and select a photo.")
            return
            
        self.btn_submit_faiss.setText("ENROLLING NOURAL DATA...")
        self.btn_submit_faiss.setDisabled(True)
        QApplication.processEvents()
        
        try:
            watchdog.enroll_face(self.selected_image_path, aadhar, name, threat, phone, address)
            QMessageBox.information(self, "Ryuk AI", f"Success: {name} is now globally recognized as {threat} threat.")
            self.name_input.clear()
            self.aadhar_input.clear()
            self.phone_input.clear()
            self.address_input.clear()
            self.selected_image_path = None
            self.img_path_label.setText("No photo selected...")
            
            # CRITICAL: Broadcast system-wide signal to restart tracking on all live cameras immediately!
            global_signals.faiss_updated.emit()
            
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
                font-family: '-apple-system', 'Segoe UI', 'SF Pro Display', sans-serif;
            }
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1b26, stop:1 #0f1015);
            }
            #Sidebar {
                background-color: rgba(20, 22, 30, 0.7);
                border-right: 1px solid rgba(255, 255, 255, 0.08);
            }
            #SidebarTitle {
                color: #FFFFFF;
                font-size: 26px;
                font-weight: 800;
                margin-bottom: 2px;
                letter-spacing: -0.5px;
            }
            #SidebarBtn, #SidebarBtnActive {
                text-align: left;
                padding: 12px 18px;
                border-radius: 12px;
                font-size: 14px;
                font-weight: 600;
                border: none;
                margin-top: 4px;
            }
            #SidebarBtn {
                color: #A0AABF;
                background: transparent;
            }
            #SidebarBtn:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: #FFFFFF;
            }
            #SidebarBtnActive {
                color: #FFFFFF;
                background-color: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
            #ContentArea {
                background-color: transparent;
            }
            #VideoCard {
                background-color: rgba(30, 32, 40, 0.6);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 16px;
            }
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 10px;
                padding: 12px;
                color: #FFFFFF;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #00E5FF;
                background-color: rgba(255, 255, 255, 0.08);
            }
            QLabel {
                color: #FFFFFF;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
