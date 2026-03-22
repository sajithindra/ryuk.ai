"""
ui/widgets/profile_row.py
Management row for each identity in the Central Intelligence list.
"""
import base64
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt


# Thread colors are now managed via QSS properties in DASHBOARD_QSS


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
        thumb_lbl.setObjectName("ProfileThumb")
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
        name_lbl.setObjectName("ProfileName")
        meta_lbl = QLabel(f"ID: {meta.get('aadhar')} | TEL: {meta.get('phone')}")
        meta_lbl.setObjectName("ProfileMeta")
        info.addWidget(name_lbl)
        info.addWidget(meta_lbl)

        # Threat badge
        threat = meta.get("threat_level", "Low")
        threat_badge = QLabel(threat.upper())
        threat_badge.setFixedSize(64, 20)
        threat_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        threat_badge.setObjectName("ThreatBadge")
        threat_badge.setProperty("threat", threat)

        # Action buttons
        def _action_btn(text: str) -> QPushButton:
            btn = QPushButton(text)
            btn.setFixedSize(70, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setObjectName("RowActionBtn")
            return btn

        btn_edit    = _action_btn("EDIT")
        btn_history = _action_btn("HISTORY")
        btn_delete  = _action_btn("DELETE")

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


