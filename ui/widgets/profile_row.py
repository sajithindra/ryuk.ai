"""
ui/widgets/profile_row.py
Management row for each identity in the Central Intelligence list.
"""
import base64
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt


def _threat_color(threat: str) -> str:
    return {"High": "#FF5370", "Medium": "#FFB74D"}.get(threat, "#00E5C8")


class ProfileRow(QFrame):
    """Premium row in the Central Intelligence registry list."""

    def __init__(self, meta: dict, on_edit, on_history, on_delete, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setStyleSheet("""
            QFrame {
                background-color: #161A25;
                border: 1px solid #2E3352;
                border-radius: 12px;
            }
            QFrame:hover {
                background-color: #1C2030;
                border-color: #404875;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(15)

        # Thumbnail
        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(40, 40)
        thumb_lbl.setStyleSheet("border-radius: 20px; background: #1C2030; border: 1.5px solid #3A4068;")
        thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t64 = meta.get("photo_thumb", "")
        if t64:
            try:
                pix = QPixmap()
                pix.loadFromData(base64.b64decode(t64))
                thumb_lbl.setPixmap(pix.scaled(40, 40,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation))
            except Exception:
                pass

        # Info column
        info = QVBoxLayout()
        name_lbl = QLabel(meta.get("name", "Unknown").upper())
        name_lbl.setStyleSheet("color: #E2E5F1; font-weight: 600; font-size: 13px; border: none;")
        meta_lbl = QLabel(f"UID: {meta.get('aadhar')} | TEL: {meta.get('phone')}")
        meta_lbl.setStyleSheet(
            "color: #6B7299; font-family: 'Roboto Mono',monospace; font-size: 10px; border: none;"
        )
        info.addWidget(name_lbl)
        info.addWidget(meta_lbl)

        # Threat badge
        threat = meta.get("threat_level", "Low")
        tc     = _threat_color(threat)
        threat_badge = QLabel(threat.upper())
        threat_badge.setFixedSize(72, 22)
        threat_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        threat_badge.setStyleSheet(f"""
            color: {tc}; background: {tc}1A;
            border: 1px solid {tc}60; border-radius: 11px;
            font-size: 10px; font-weight: 700; letter-spacing: 0.5px;
        """)

        # Action buttons
        def _action_btn(text: str, color: str) -> QPushButton:
            btn = QPushButton(text)
            btn.setFixedSize(75, 30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba({_hex_to_rgb(color)}, 0.08);
                    color: {color};
                    border: 1px solid rgba({_hex_to_rgb(color)}, 0.25);
                    border-radius: 15px;
                    font-size: 10px; font-weight: 600;
                }}
                QPushButton:hover {{ background: rgba({_hex_to_rgb(color)}, 0.16); }}
            """)
            return btn

        btn_edit    = _action_btn("EDIT",    "#00E5FF")
        btn_history = _action_btn("HISTORY", "#7B8FD4")
        btn_delete  = _action_btn("DELETE",  "#FF5370")

        btn_edit.clicked.connect(on_edit)
        btn_history.clicked.connect(on_history)
        btn_delete.clicked.connect(on_delete)

        layout.addWidget(thumb_lbl)
        layout.addLayout(info, 1)
        layout.addWidget(threat_badge)
        layout.addSpacing(10)
        layout.addWidget(btn_edit)
        layout.addWidget(btn_history)
        layout.addWidget(btn_delete)


def _hex_to_rgb(hex_color: str) -> str:
    """Convert #RRGGBB → 'R, G, B' string for rgba() CSS."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r}, {g}, {b}"
