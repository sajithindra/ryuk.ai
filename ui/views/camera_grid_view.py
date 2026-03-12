"""
ui/views/camera_grid_view.py
God's Eye live camera grid — scroll area with 2-column grid layout.
"""
from PyQt6.QtWidgets import (
    QScrollArea, QWidget, QGridLayout, QLabel,
)
from PyQt6.QtCore import Qt


class CameraGridView(QScrollArea):
    """Scrollable grid of CameraCard widgets. Manages empty-state label."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setObjectName("ContentArea")
        self.setStyleSheet("border: none;")

        self._container = QWidget()
        self.grid = QGridLayout(self._container)
        self.grid.setContentsMargins(24, 24, 24, 24)
        self.grid.setSpacing(20)
        self.setWidget(self._container)

        # Empty state
        self.empty_label = QLabel("No active streams")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #475569; font-size: 14px;")
        self.grid.addWidget(self.empty_label, 0, 0)
        self._card_count = 0

    def add_card(self, card):
        """Add a CameraCard at the next grid position (2-column layout)."""
        if self._card_count == 0:
            self.grid.removeWidget(self.empty_label)
            self.empty_label.hide()
        row = self._card_count // 2
        col = self._card_count % 2
        self.grid.addWidget(card, row, col)
        self._card_count += 1

    def remove_card(self, card):
        """Remove a CameraCard and show empty state if grid is now empty."""
        self.grid.removeWidget(card)
        card.deleteLater()
        self._card_count -= 1
        if self._card_count <= 0:
            self._card_count = 0
            self.grid.addWidget(self.empty_label, 0, 0)
            self.empty_label.show()
