"""
ui/widgets/system_health.py
Compact status bar showing Redis + MongoDB connectivity.
"""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel


class SystemHealthIndicator(QFrame):
    """Compact rail element showing coloured dots for Redis + MongoDB."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setStyleSheet("background: transparent; border-top: 1px solid #2E3352;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)

        self.lbl_redis = QLabel("● REDIS")
        self.lbl_redis.setStyleSheet(
            "color: #00E5FF; font-size: 9px; font-weight: 600; border: none; letter-spacing: 0.5px;"
        )
        self.lbl_mongo = QLabel("● MONGO")
        self.lbl_mongo.setStyleSheet(
            "color: #00E5FF; font-size: 9px; font-weight: 600; border: none; letter-spacing: 0.5px;"
        )

        lay.addWidget(self.lbl_redis)
        lay.addSpacing(12)
        lay.addWidget(self.lbl_mongo)
        lay.addStretch()

    def update_status(self, redis_ok: bool, mongo_ok: bool):
        _ok, _err = "#00E5FF", "#FF5370"
        self.lbl_redis.setText(f"{'●' if redis_ok else '○'} REDIS")
        self.lbl_redis.setStyleSheet(
            f"color: {_ok if redis_ok else _err}; font-size: 9px; font-weight: 600; border: none;"
        )
        self.lbl_mongo.setText(f"{'●' if mongo_ok else '○'} MONGO")
        self.lbl_mongo.setStyleSheet(
            f"color: {_ok if mongo_ok else _err}; font-size: 9px; font-weight: 600; border: none;"
        )
