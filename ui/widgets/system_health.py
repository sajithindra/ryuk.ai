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
        self.setObjectName("SystemHealth")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)

        self.lbl_redis = QLabel("REDIS")
        self.lbl_redis.setObjectName("HealthLabel")
        self.lbl_mongo = QLabel("MONGO")
        self.lbl_mongo.setObjectName("HealthLabel")

        lay.addWidget(self.lbl_redis)
        lay.addSpacing(12)
        lay.addWidget(self.lbl_mongo)
        lay.addStretch()

    def update_status(self, redis_ok: bool, mongo_ok: bool):
        _ok, _err = "#10B981", "#EF4444"
        self.lbl_redis.setStyleSheet(f"color: {_ok if redis_ok else _err}; font-weight: 600; font-size: 10px;")
        self.lbl_mongo.setStyleSheet(f"color: {_ok if mongo_ok else _err}; font-weight: 600; font-size: 10px;")
