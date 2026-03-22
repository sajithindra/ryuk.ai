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
        self.lbl_redis.setProperty("status", "online" if redis_ok else "offline")
        self.lbl_mongo.setProperty("status", "online" if mongo_ok else "offline")
        
        # Refresh styles
        for lbl in [self.lbl_redis, self.lbl_mongo]:
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
