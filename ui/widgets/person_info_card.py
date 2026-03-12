"""
ui/widgets/person_info_card.py
Intelligence blade card shown in the sliding intel panel.
"""
import base64
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt


def _threat_color(threat: str) -> str:
    return {"High": "#FF5370", "Medium": "#FFB74D"}.get(threat, "#00E5C8")


class PersonInfoCard(QFrame):
    """Intelligence card for the right-side detection panel."""

    def __init__(self, meta: dict, parent=None):
        super().__init__(parent)
        threat = meta.get("threat_level", "Low")
        tc     = _threat_color(threat)

        self.setObjectName("PersonCard")
        # Keep threat dynamic indicator on the left
        self.setStyleSheet(f"border-left: 2px solid {tc};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        photo = QLabel()
        photo.setFixedSize(48, 48)
        photo.setObjectName("PersonPhoto")
        photo.setStyleSheet(f"border: 1px solid {tc}; border-radius: 24px; background: #0F111A;")
        
        thumb = meta.get("photo_thumb", "")
        if thumb:
            try:
                pix = QPixmap()
                pix.loadFromData(base64.b64decode(thumb))
                photo.setPixmap(pix.scaled(48, 48,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation))
            except Exception: pass

        name_col = QVBoxLayout()
        lbl_sub  = QLabel("IDENTIFIED")
        lbl_sub.setStyleSheet("color: #64748B; font-size: 9px; font-weight: 600; letter-spacing: 1px;")
        lbl_name = QLabel(meta.get("name", "Unknown Target").upper())
        lbl_name.setStyleSheet("color: #F8FAFC; font-weight: 600; font-size: 14px;")
        name_col.addWidget(lbl_sub)
        name_col.addWidget(lbl_name)

        badge = QLabel(threat.upper())
        badge.setFixedSize(64, 20)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"background: {tc}20; color: {tc}; border-radius: 4px; font-size: 9px; font-weight: 600;")

        hdr.addWidget(photo)
        hdr.addSpacing(10)
        hdr.addLayout(name_col)
        hdr.addStretch()
        hdr.addWidget(badge)
        layout.addLayout(hdr)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #1E293B;")
        layout.addWidget(sep)

        # Attributes
        for label, value, mono in [
            ("ID",      meta.get("aadhar", "N/A"),  True),
            ("MOBILE",  meta.get("phone", "N/A"),   True),
            ("LOCATION", meta.get("address", "N/A"), False),
        ]:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            lk = QLabel(label)
            lk.setStyleSheet("color: #64748B; font-weight: 600; font-size: 9px;")
            lk.setFixedWidth(50)
            lv = QLabel(str(value))
            lv.setStyleSheet("color: #CBD5E1; font-size: 12px;")
            lv.setWordWrap(True)
            rl.addWidget(lk)
            rl.addWidget(lv, 1)
            layout.addWidget(row)
