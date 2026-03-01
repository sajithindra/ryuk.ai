"""
ui/dialogs/edit_profile_dialog.py
Overlay dialog to edit an existing biometric profile.
"""
import base64

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton,
)
from PyQt6.QtGui import QPixmap, QPainter, QBrush
from PyQt6.QtCore import Qt

import core.watchdog_indexer as watchdog


class EditProfileDialog(QMainWindow):
    """Sleek overlay to edit name/phone/address/threat of a profile."""

    def __init__(self, meta: dict, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setWindowTitle("EDIT BIOMETRIC PROFILE")
        self.setFixedSize(400, 560)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet("""
            QMainWindow { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #1a1b26,stop:1 #0f1015); }
            QWidget { font-family: 'Segoe UI','SF Pro Display',sans-serif; }
            QLineEdit {
                background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
                border-radius: 8px; padding: 12px; color: #FFF; font-size: 13px;
            }
            QLineEdit:focus { border-color: #00E5FF; }
            QLabel { color: #E2E5F1; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(30, 30, 30, 30)
        lay.setSpacing(12)

        hdr = QLabel("UPDATE PROFILE")
        hdr.setStyleSheet("color: #00E5FF; font-weight: 800; font-size: 18px;")
        lay.addWidget(hdr)

        # Circular photo
        photo = QLabel()
        photo.setFixedSize(90, 90)
        photo.setStyleSheet("border-radius: 45px; background: #16191E; border: 2px solid #2D3139;")
        photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb = meta.get("photo_thumb", "")
        if thumb:
            try:
                pix = QPixmap()
                pix.loadFromData(base64.b64decode(thumb))
                scaled = pix.scaled(90, 90,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
                photo.setPixmap(scaled)
                mask = QPixmap(90, 90)
                mask.fill(Qt.GlobalColor.transparent)
                p = QPainter(mask)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setBrush(QBrush(Qt.GlobalColor.black))
                p.drawEllipse(0, 0, 90, 90)
                p.end()
                photo.setMask(mask.mask())
            except Exception:
                pass
        lay.addWidget(photo, 0, Qt.AlignmentFlag.AlignHCenter)

        self.name_in    = QLineEdit(meta.get("name", ""))
        self.name_in.setPlaceholderText("Name")
        self.phone_in   = QLineEdit(meta.get("phone", ""))
        self.phone_in.setPlaceholderText("Phone")
        self.address_in = QLineEdit(meta.get("address", ""))
        self.address_in.setPlaceholderText("Address")

        self.threat_in = QComboBox()
        self.threat_in.addItems(["Low", "Medium", "High"])
        self.threat_in.setCurrentText(meta.get("threat_level", "Low"))
        self.threat_in.setStyleSheet(
            "background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);"
            "border-radius: 8px; padding: 12px; color: #FFF;"
        )

        for lbl, widget in [
            ("FULL NAME", self.name_in), ("PHONE", self.phone_in),
            ("RESIDENCE", self.address_in), ("SECURITY CLEARANCE", self.threat_in),
        ]:
            l = QLabel(lbl)
            l.setStyleSheet("color: #6B7299; font-size: 10px; font-weight: 600; letter-spacing: 0.5px;")
            lay.addWidget(l)
            lay.addWidget(widget)

        lay.addStretch()

        btn = QPushButton("SAVE CHANGES")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton { background: #00E5FF; color: #003E45; font-weight: 700; padding: 14px; border-radius: 8px; border: none; }
            QPushButton:hover { background: #33EAFF; }
        """)
        btn.clicked.connect(self._save)
        lay.addWidget(btn)

    def _save(self, checked=False):
        watchdog.update_profile(self.meta["aadhar"], {
            "name":         self.name_in.text(),
            "phone":        self.phone_in.text(),
            "address":      self.address_in.text(),
            "threat_level": self.threat_in.currentText(),
        })
        self.close()
