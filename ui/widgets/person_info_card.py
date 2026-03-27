"""
ui/widgets/person_info_card.py
Intelligence blade card shown in the sliding intel panel.
"""
import base64
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt


def _threat_color(threat: str) -> str:
    return {"High": "#EF4444", "Medium": "#F59E0B"}.get(threat, "#3D7BFF")


class PersonInfoCard(QFrame):
    """Intelligence card for the right-side detection panel."""

    def __init__(self, meta: dict, parent=None):
        super().__init__(parent)
        threat = meta.get("threat_level", "Low")
        tc     = _threat_color(threat)

        self.setObjectName("PersonCard")
        self.setProperty("threat", threat)
        # Apply property-based style refresh
        self.style().unpolish(self)
        self.style().polish(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        photo = QLabel()
        photo.setFixedSize(48, 48)
        photo.setObjectName("PersonPhoto")
        photo.setProperty("threat", threat)
        
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
        lbl_sub.setObjectName("IdentifiedSub")
        lbl_name = QLabel(meta.get("name", "Unknown Target").upper())
        lbl_name.setObjectName("IdentifiedName")
        name_col.addWidget(lbl_sub)
        name_col.addWidget(lbl_name)

        badge = QLabel(threat.upper())
        badge.setObjectName("ThreatBadge")
        badge.setFixedSize(64, 20)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setProperty("threat", threat)

        hdr.addWidget(photo)
        hdr.addSpacing(10)
        hdr.addLayout(name_col)
        hdr.addStretch()
        
        # Count label (initially hidden)
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("CountLabel")
        self.count_lbl.setStyleSheet("color: #3D7BFF; font-weight: 800; font-size: 14px;")
        hdr.addWidget(self.count_lbl)
        hdr.addSpacing(10)
        
        hdr.addWidget(badge)
        layout.addLayout(hdr)
        
        if meta.get("is_object"):
            self.count_lbl.setText(str(meta.get("count", 1)))
            # Change icon for object (though it's a photo label here)
            # We could draw a category icon if photo is missing.
            if not thumb:
                 photo.setText("OBJ")
                 photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
                 photo.setStyleSheet("background: #111; color: #3D7BFF; font-weight: 900; border-radius: 4px;")

        sep = QFrame()
        sep.setObjectName("CardSeparator")
        sep.setFixedHeight(1)
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
            lk.setObjectName("AttributeLabel")
            lk.setFixedWidth(60)
            lv = QLabel(str(value))
            lv.setObjectName("AttributeValue")
            lv.setWordWrap(True)
            rl.addWidget(lk)
            rl.addWidget(lv, 1)
            layout.addWidget(row)

    def update_count(self, count: int):
        self.count_lbl.setText(str(count))
        # Pulsing effect or color change could be added here
