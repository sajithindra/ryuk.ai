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
    """Management row in the Central Intelligence registry list."""

    def __init__(self, meta: dict, on_edit, on_history, on_delete, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setObjectName("PersonCard")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(15)

        # Thumbnail
        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(40, 40)
        thumb_lbl.setStyleSheet("border-radius: 20px; background: #0F111A; border: 1px solid #334155;")
        thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t64 = meta.get("photo_thumb", "")
        if t64:
            try:
                pix = QPixmap()
                pix.loadFromData(base64.b64decode(t64))
                thumb_lbl.setPixmap(pix.scaled(40, 40,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation))
            except Exception: pass

        # Info column
        info = QVBoxLayout()
        name_lbl = QLabel(meta.get("name", "Unknown").upper())
        name_lbl.setStyleSheet("color: #F8FAFC; font-weight: 600; font-size: 13px;")
        meta_lbl = QLabel(f"ID: {meta.get('aadhar')} | TEL: {meta.get('phone')}")
        meta_lbl.setStyleSheet("color: #64748B; font-size: 10px;")
        info.addWidget(name_lbl)
        info.addWidget(meta_lbl)

        # Threat badge
        threat = meta.get("threat_level", "Low")
        tc     = _threat_color(threat)
        threat_badge = QLabel(threat.upper())
        threat_badge.setFixedSize(64, 20)
        threat_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        threat_badge.setStyleSheet(f"color: {tc}; background: {tc}15; border-radius: 4px; font-size: 9px; font-weight: 600;")

        # Action buttons
        def _action_btn(text: str, color: str) -> QPushButton:
            btn = QPushButton(text)
            btn.setFixedSize(70, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #1A1D2B;
                    color: {color};
                    border: 1px solid #334155;
                    border-radius: 4px;
                    font-size: 9px; font-weight: 600;
                }}
                QPushButton:hover {{ border-color: {color}; background: {color}10; }}
            """)
            return btn

        btn_edit    = _action_btn("EDIT",    "#3B82F6")
        btn_history = _action_btn("HISTORY", "#94A3B8")
        btn_delete  = _action_btn("DELETE",  "#EF4444")

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


