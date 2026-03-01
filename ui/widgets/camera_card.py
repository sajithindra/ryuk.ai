"""
ui/widgets/camera_card.py
Reusable camera stream card with LIVE badge and fps counter.
"""
import time
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget
from PyQt6.QtCore import Qt


class CameraCard(QFrame):
    """A reusable UI card for a single camera stream."""

    def __init__(self, client_id: str, parent=None):
        super().__init__(parent)
        self.client_id        = client_id
        self._last_frame_time = None
        self._frame_count     = 0
        self.setObjectName("VideoCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        # ── Header row ────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        self.lbl_id = QLabel(f"⊞  {client_id.upper()}")
        self.lbl_id.setStyleSheet(
            "color: #00E5FF; font-family: 'Roboto Mono','Ubuntu Mono',monospace;"
            "font-size: 10px; font-weight: 600; letter-spacing: 1px; border: none;"
        )
        hdr.addWidget(self.lbl_id)
        hdr.addStretch()
        outer.addLayout(hdr)

        # ── Video area with footer overlay ────────────────────────────
        video_stack = QWidget()
        video_stack.setStyleSheet("background: transparent; border: none;")
        stack_lay = QVBoxLayout(video_stack)
        stack_lay.setContentsMargins(0, 0, 0, 0)
        stack_lay.setSpacing(0)

        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet(
            "background: #080A0F; border-radius: 10px; border: 1px solid #2E3352;"
        )
        self.video_label.setMinimumSize(480, 340)

        # Footer overlay (LIVE badge + fps)
        footer = QFrame()
        footer.setFixedHeight(28)
        footer.setStyleSheet(
            "background: rgba(8,10,15,0.72); border: none;"
            "border-bottom-left-radius: 10px; border-bottom-right-radius: 10px;"
        )
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(10, 0, 10, 0)

        self.live_badge = QLabel("● LIVE")
        self.live_badge.setStyleSheet(
            "color: #FF5370; font-size: 10px; font-weight: 700;"
            "letter-spacing: 0.5px; border: none; background: transparent;"
        )
        self.fps_label = QLabel("-- fps")
        self.fps_label.setStyleSheet(
            "color: #6B7299; font-size: 10px; font-family: 'Roboto Mono',monospace;"
            "border: none; background: transparent;"
        )
        f_lay.addWidget(self.live_badge)
        f_lay.addStretch()
        f_lay.addWidget(self.fps_label)

        stack_lay.addWidget(self.video_label, 1)
        stack_lay.addWidget(footer)
        outer.addWidget(video_stack, 1)

    def update_fps(self):
        """Call on every new frame to compute and display fps."""
        now = time.time()
        self._frame_count += 1
        if self._last_frame_time is not None:
            elapsed = now - self._last_frame_time
            if elapsed > 0:
                self.fps_label.setText(f"{1.0 / elapsed:.0f} fps")
        self._last_frame_time = now
