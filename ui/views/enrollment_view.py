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
        t.setStyleSheet("color: #E2E5F1; font-size: 20px; font-weight: 700; letter-spacing: 1px;")
        s = QLabel("Register a new identity into the global recognition network")
        s.setStyleSheet("color: #6B7299; font-size: 12px;")
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
            background: #0D0F1A; border: 2px dashed #2E3352;
            border-radius: 16px; color: #3A4068; font-size: 40px;
        """)

        btn_browse = QPushButton("📁  SELECT PHOTO")
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.setStyleSheet("""
            QPushButton {
                background: transparent; border: 1.5px solid #3A4068;
                color: #6B7299; border-radius: 8px; padding: 12px;
                font-size: 12px; font-weight: 600;
            }
            QPushButton:hover { border-color: #00E5FF; color: #00E5FF; background: rgba(0,229,255,0.04); }
        """)
        btn_browse.clicked.connect(self._browse)

        self.img_path_label = QLabel("No photo selected")
        self.img_path_label.setStyleSheet(
            "color: #3A4068; font-size: 10px; font-family: 'Roboto Mono',monospace; border: none;"
        )
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
        form.setStyleSheet("background: #111420; border-radius: 16px; border: 1px solid #2E3352;")
        fl = QVBoxLayout(form)
        fl.setContentsMargins(32, 32, 32, 32)
        fl.setSpacing(14)

        def _sec(txt):
            l = QLabel(txt)
            l.setStyleSheet(
                "color: #3A4068; font-size: 10px; font-weight: 700;"
                "letter-spacing: 1.5px; border: none; margin-top: 8px;"
            )
            return l

        self.name_input    = QLineEdit(); self.name_input.setPlaceholderText("Full Name")
        self.aadhar_input  = QLineEdit(); self.aadhar_input.setPlaceholderText("Aadhar (xxxx-xxxx-xxxx)")
        self.phone_input   = QLineEdit(); self.phone_input.setPlaceholderText("Phone (+91-xxxx-xxxxxx)")
        self.address_input = QLineEdit(); self.address_input.setPlaceholderText("Residence Address")

        self.threat_input = QComboBox()
        self.threat_input.addItems(["Low", "Medium", "High"])
        self.threat_input.setStyleSheet(
            "background-color: #1C2030; border: 1.5px solid #3A4068;"
            "border-radius: 8px; padding: 12px 16px; color: #E2E5F1;"
        )

        self.btn_submit = QPushButton("ENROLL IDENTITY")
        self.btn_submit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_submit.setStyleSheet("""
            QPushButton {
                background-color: #00E5FF; color: #003E45;
                font-weight: 700; font-size: 14px; letter-spacing: 0.5px;
                padding: 16px; border-radius: 10px; border: none; margin-top: 8px;
            }
            QPushButton:hover   { background-color: #33EAFF; }
            QPushButton:pressed { background-color: #00B8CC; }
            QPushButton:disabled { background-color: #1C2030; color: #3A4068; }
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
                    "background: #0D0F1A; border: 2px solid #00E5FF; border-radius: 16px;"
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
            background: #0D0F1A; border: 2px dashed #2E3352;
            border-radius: 16px; color: #3A4068; font-size: 40px;
        """)
