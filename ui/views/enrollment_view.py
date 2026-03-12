"""
ui/views/enrollment_view.py
Two-column Watchdog Enrollment form (photo preview + input fields).
Emits enrolled(aadhar, name) after successful enrollment.
"""
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QFileDialog, QMessageBox,
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

import core.watchdog_indexer as watchdog
from core.state import global_signals
from ui.widgets.enrollment_worker import EnrollmentWorker


class EnrollmentView(QFrame):
    """Two-column enrolment form: photo preview on left, fields on right."""

    enrolled = pyqtSignal()   # fired after a successful enrolment

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentArea")
        self._selected_image: str | None = None
        self._worker: EnrollmentWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(24)

        # Header
        hdr = QVBoxLayout()
        t = QLabel("WATCHDOG ENROLLMENT")
        t.setStyleSheet("color: #F8FAFC; font-size: 18px; font-weight: 700;")
        s = QLabel("Register a new identity into the recognition network")
        s.setStyleSheet("color: #64748B; font-size: 12px;")
        hdr.addWidget(t)
        hdr.addWidget(s)
        outer.addLayout(hdr)

        # Two-column body
        cols = QHBoxLayout()
        cols.setSpacing(20)
        cols.addLayout(self._build_photo_col(), 0)
        cols.addLayout(self._build_form_col(), 1)
        outer.addLayout(cols, 1)

    # ------------------------------------------------------------------
    # Column builders
    # ------------------------------------------------------------------

    def _build_photo_col(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(12)

        self.photo_preview = QLabel("☻")
        self.photo_preview.setFixedSize(220, 220)
        self.photo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo_preview.setStyleSheet("""
            background: #1A1D2B; border: 1px dashed #334155;
            border-radius: 12px; color: #334155; font-size: 40px;
        """)

        btn_browse = QPushButton("SELECT PHOTO")
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.setStyleSheet("""
            QPushButton {
                background: #1A1D2B; border: 1px solid #334155;
                color: #94A3B8; border-radius: 6px; padding: 10px;
                font-size: 11px; font-weight: 600;
            }
            QPushButton:hover { border-color: #3B82F6; color: #3B82F6; }
        """)
        btn_browse.clicked.connect(self._browse)

        self.img_path_label = QLabel("No photo selected")
        self.img_path_label.setStyleSheet("color: #475569; font-size: 10px;")
        self.img_path_label.setWordWrap(True)
        self.img_path_label.setMaximumWidth(220)

        col.addStretch()
        col.addWidget(self.photo_preview, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(btn_browse)
        col.addWidget(self.img_path_label, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addStretch()
        return col

    def _build_form_col(self) -> QVBoxLayout:
        col = QVBoxLayout()

        form = QFrame()
        form.setStyleSheet("background: #1A1D2B; border-radius: 12px; border: 1px solid #2D3748;")
        fl = QVBoxLayout(form)
        fl.setContentsMargins(32, 32, 32, 32)
        fl.setSpacing(14)

        def _sec(txt):
            l = QLabel(txt)
            l.setStyleSheet("color: #475569; font-size: 10px; font-weight: 700; letter-spacing: 1px; margin-top: 8px;")
            return l

        self.name_input    = QLineEdit(); self.name_input.setPlaceholderText("Full Name")
        self.aadhar_input  = QLineEdit(); self.aadhar_input.setPlaceholderText("Aadhar (xxxx-xxxx-xxxx)")
        self.phone_input   = QLineEdit(); self.phone_input.setPlaceholderText("Phone (+91-xxxx-xxxxxx)")
        self.address_input = QLineEdit(); self.address_input.setPlaceholderText("Residence Address")

        self.threat_input = QComboBox()
        self.threat_input.addItems(["Low", "Medium", "High"])

        self.btn_submit = QPushButton("ENROLL IDENTITY")
        self.btn_submit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_submit.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6; color: #FFFFFF;
                font-weight: 600; font-size: 13px;
                padding: 14px; border-radius: 6px; border: none; margin-top: 8px;
            }
            QPushButton:hover { background-color: #2563EB; }
            QPushButton:disabled { background-color: #1E293B; color: #475569; }
        """)
        self.btn_submit.clicked.connect(self._submit)

        fl.addWidget(_sec("IDENTITY DETAILS"))
        fl.addWidget(self.name_input)
        fl.addWidget(self.aadhar_input)
        fl.addWidget(self.phone_input)
        fl.addWidget(self.address_input)
        fl.addWidget(_sec("THREAT CLASSIFICATION"))
        fl.addWidget(self.threat_input)
        fl.addWidget(self.btn_submit)

        col.addWidget(form)
        col.addStretch()
        return col

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _browse(self, checked=False):
        fn, _ = QFileDialog.getOpenFileName(
            self, "Select Face Identity", "", "Image Files (*.png *.jpg *.jpeg)"
        )
        if fn:
            self._selected_image = fn
            self.img_path_label.setText(fn.split("/")[-1])
            try:
                pix = QPixmap(fn)
                self.photo_preview.setPixmap(
                    pix.scaled(220, 220,
                               Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
                )
                self.photo_preview.setStyleSheet(
                    "background: #1A1D2B; border: 1px solid #3B82F6; border-radius: 12px;"
                )
            except Exception:
                pass

    def _submit(self, checked=False):
        aadhar  = self.aadhar_input.text().strip()
        name    = self.name_input.text().strip()
        phone   = self.phone_input.text().strip()
        address = self.address_input.text().strip()
        threat  = self.threat_input.currentText()

        if not name or not aadhar or not self._selected_image:
            QMessageBox.warning(self, "Input Error", "Please fill name, Aadhar, and select a photo.")
            return

        self.btn_submit.setText("ENROLLING NEURAL DATA…")
        self.btn_submit.setDisabled(True)

        self._worker = EnrollmentWorker(
            self._selected_image, aadhar, name, threat, phone, address
        )
        self._worker.success.connect(self._on_success)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_success(self, msg: str):
        QMessageBox.information(self, "Ryuk AI", msg)
        self._clear_form()
        global_signals.faiss_updated.emit()
        self.enrolled.emit()

    def _on_error(self, msg: str):
        QMessageBox.critical(self, "Enrollment Error", msg)

    def _on_done(self):
        self.btn_submit.setText("ENROLL IDENTITY")
        self.btn_submit.setDisabled(False)

    def _clear_form(self):
        self.name_input.clear()
        self.aadhar_input.clear()
        self.phone_input.clear()
        self.address_input.clear()
        self._selected_image = None
        self.img_path_label.setText("No photo selected")
        self.photo_preview.setText("☻")
        self.photo_preview.setStyleSheet("""
            background: #1A1D2B; border: 1px dashed #334155;
            border-radius: 12px; color: #334155; font-size: 40px;
        """)
