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
    """Premium intelligence blade for the right-side detection panel."""

    def __init__(self, meta: dict, parent=None):
        super().__init__(parent)
        threat = meta.get("threat_level", "Low")
        tc     = _threat_color(threat)

        self.setStyleSheet(f"""
            QFrame {{
                background-color: #161A25;
                border: 1px solid #2E3352;
                border-left: 3px solid {tc};
                border-radius: 12px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        photo = QLabel()
        photo.setFixedSize(50, 50)
        photo.setStyleSheet(f"border: 2px solid {tc}; border-radius: 25px; background: #1C2030;")
        thumb = meta.get("photo_thumb", "")
        if thumb:
            try:
                pix = QPixmap()
                pix.loadFromData(base64.b64decode(thumb))
                photo.setPixmap(pix.scaled(50, 50,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation))
            except Exception:
                pass

        name_col = QVBoxLayout()
        lbl_sub  = QLabel("BIOMETRIC IDENTIFIED")
        lbl_sub.setStyleSheet("color: #6B7299; font-size: 9px; font-weight: 600; letter-spacing: 1.5px; border: none;")
        lbl_name = QLabel(meta.get("name", "Unknown Target").upper())
        lbl_name.setStyleSheet("color: #FFFFFF; font-weight: 700; font-size: 15px; border: none;")
        name_col.addWidget(lbl_sub)
        name_col.addWidget(lbl_name)

        badge = QLabel(threat.upper())
        badge.setFixedSize(72, 24)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"""
            background: {tc}1A; color: {tc};
            border: 1px solid {tc}60;
            border-radius: 12px; font-size: 10px; font-weight: 700;
        """)

        hdr.addWidget(photo)
        hdr.addSpacing(10)
        hdr.addLayout(name_col)
        hdr.addStretch()
        hdr.addWidget(badge)
        layout.addLayout(hdr)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #2E3352; border: none;")
        layout.addWidget(sep)

        # Attributes
        for label, value, mono in [
            ("UID",    meta.get("aadhar", "N/A"),  True),
            ("MOBILE", meta.get("phone", "N/A"),   True),
            ("LOC",    meta.get("address", "N/A"), False),
        ]:
            row = QWidget()
            row.setStyleSheet("background: transparent; border: none;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            lk = QLabel(label)
            lk.setStyleSheet("color: #6B7299; font-weight: 600; font-size: 10px; letter-spacing: 0.5px; border: none;")
            lk.setFixedWidth(60)
            font = "font-family: 'Roboto Mono',monospace; " if mono else ""
            lv = QLabel(str(value))
            lv.setStyleSheet(f"color: #C5C9E0; {font}font-size: 12px; border: none;")
            lv.setWordWrap(True)
            rl.addWidget(lk)
            rl.addWidget(lv, 1)
            layout.addWidget(row)

        layout.addSpacing(4)
