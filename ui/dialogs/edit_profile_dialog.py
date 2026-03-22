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
        self.setObjectName("EditProfileDialog")
        self.setWindowTitle("EDIT BIOMETRIC PROFILE")
        self.setFixedSize(400, 560)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)

        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(30, 30, 30, 30)
        lay.setSpacing(12)

        hdr = QLabel("UPDATE PROFILE")
        hdr.setObjectName("DialogHeader")
        lay.addWidget(hdr)

        # Circular photo
        photo = QLabel()
        photo.setFixedSize(90, 90)
        photo.setObjectName("DialogPhoto")
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

        for lbl, widget in [
            ("FULL NAME", self.name_in), ("PHONE", self.phone_in),
            ("RESIDENCE", self.address_in), ("SECURITY CLEARANCE", self.threat_in),
        ]:
            l = QLabel(lbl)
            l.setObjectName("DialogLabel")
            lay.addWidget(l)
            lay.addWidget(widget)

        lay.addStretch()

        btn = QPushButton("SAVE CHANGES")
        btn.setObjectName("ActionBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
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
