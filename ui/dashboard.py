"""
ui/dashboard.py — DashboardWindow orchestrator
After the modularity refactor this file is ~350 lines.
All business logic / UI components live in their respective modules:
  ui/styles.py                    — DASHBOARD_QSS stylesheet
  ui/widgets/camera_card.py       — CameraCard
  ui/widgets/person_info_card.py  — PersonInfoCard
  ui/widgets/system_health.py     — SystemHealthIndicator
  ui/widgets/enrollment_worker.py — EnrollmentWorker
  ui/widgets/profile_row.py       — ProfileRow
  ui/views/camera_grid_view.py    — CameraGridView
  ui/views/enrollment_view.py     — EnrollmentView
  ui/views/ci_view.py             — CIView
  ui/dialogs/activity_report_dialog.py — ActivityReportDialog
  ui/dialogs/edit_profile_dialog.py    — EditProfileDialog
  core/watchdog_indexer.py        — WatchdogIndexer (singleton)
  components/video_worker.py      — VideoProcessor
  components/face_tracker.py      — FaceTracker
"""

import time
import json
import socket
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QStackedWidget,
    QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
)
from PyQt6.QtGui import QPixmap, QImage

# ── New module imports ──────────────────────────────────────────────
from ui.styles                        import DASHBOARD_QSS
from ui.widgets.camera_card           import CameraCard
from ui.widgets.person_info_card      import PersonInfoCard
from ui.widgets.system_health         import SystemHealthIndicator
from ui.views.camera_grid_view        import CameraGridView
from ui.views.enrollment_view         import EnrollmentView
from ui.views.ci_view                 import CIView
# ────────────────────────────────────────────────────────────────────

import core.watchdog_indexer as watchdog
from core.state              import new_stream_signals, cache, cache_str, global_signals
from components.video_worker import VideoProcessor
from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT,
    POLL_INTERVAL_MS, ALERT_INTERVAL_MS,
    CLEANUP_INTERVAL_MS, HEALTH_INTERVAL_MS,
    INTEL_CLEANUP_S, INTEL_PANEL_WIDTH,
    SERVER_PORT
)


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


class DashboardWindow(QMainWindow):
    """
    Top-level application window.
    Owns the top-bar, nav-rail, stacked views, and intel panel.
    All form/list logic is delegated to view sub-components.
    """

    def __init__(self, ip_address=None):
        super().__init__()
        self.ip_address = ip_address or _get_local_ip()
        self.setWindowTitle("Ryuk AI — Command Center")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        # Session state
        self.active_sessions:   dict = {}
        self.active_intel_cards: dict = {}
        self.intel_last_seen:   dict = {}

        # Redis pub/sub for alert stream
        self.pubsub = cache.pubsub()
        self.pubsub.subscribe("security_alerts")

        self._build_ui()
        self.apply_styles()
        self._start_timers()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Alert banner (hidden initially)
        self.alert_banner, self.alert_label = self._build_alert_banner()
        root.addWidget(self.alert_banner)

        # Top command bar
        self.top_bar, self.clock_lbl, self.page_title_lbl, \
            self.tb_redis, self.tb_mongo = self._build_top_bar()
        root.addWidget(self.top_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Nav rail
        self.nav_rail, nav_btns, self.health_indicator = self._build_nav_rail()
        self.btn_cameras, self.btn_watchdog, self.btn_reports, self.btn_settings = nav_btns
        body.addWidget(self.nav_rail)

        # Stacked views
        self.stacked = QStackedWidget()
        self.grid_view       = CameraGridView()
        self.enrollment_view = EnrollmentView()
        self.ci_view         = CIView()
        settings_placeholder = QWidget()
        self.stacked.addWidget(self.grid_view)        # 0
        self.stacked.addWidget(self.enrollment_view)  # 1
        self.stacked.addWidget(self.ci_view)          # 2
        self.stacked.addWidget(settings_placeholder)  # 3
        body.addWidget(self.stacked, 1)

        # Intel panel
        self.intel_panel, self.intel_list_layout, \
            self.intel_animation, self.intel_min_anim = self._build_intel_panel()
        body.addWidget(self.intel_panel)

        root.addLayout(body, 1)

    def _build_alert_banner(self):
        banner = QFrame()
        banner.setObjectName("AlertBanner")
        banner.setFixedHeight(56)
        banner.hide()
        lay = QHBoxLayout(banner)
        label = QLabel("⚠  SECURITY ALERT")
        label.setObjectName("AlertLabel")
        btn = QPushButton("DISMISS")
        btn.setObjectName("AlertDismissBtn")
        btn.setFixedWidth(90)
        btn.clicked.connect(banner.hide)
        lay.addSpacing(16); lay.addWidget(label); lay.addStretch()
        lay.addWidget(btn); lay.addSpacing(16)
        return banner, label

    def _build_top_bar(self):
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(48)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)

        logo = QLabel("RYUK")
        logo.setObjectName("Logo")

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setObjectName("TopBarSeparator")
        sep.setFixedWidth(1)

        page_title = QLabel("CAMERA GRID")
        page_title.setObjectName("PageTitle")

        clock = QLabel()
        clock.setObjectName("Clock")

        url_lbl = QLabel(f"{self.ip_address}:{SERVER_PORT}")
        url_lbl.setObjectName("UrlLabel")

        tb_redis = QLabel("● REDIS")
        tb_redis.setObjectName("StatusLabel")
        tb_mongo = QLabel("● MONGO")
        tb_mongo.setObjectName("StatusLabel")

        lay.addWidget(logo)
        lay.addSpacing(12)
        lay.addWidget(sep)
        lay.addSpacing(12)
        lay.addWidget(page_title)
        lay.addStretch()
        lay.addWidget(url_lbl)
        lay.addSpacing(20)
        lay.addWidget(tb_redis)
        lay.addSpacing(12)
        lay.addWidget(tb_mongo)
        lay.addSpacing(20)
        lay.addWidget(clock)

        return bar, clock, page_title, tb_redis, tb_mongo

    def _build_nav_rail(self):
        rail = QFrame()
        rail.setObjectName("NavRail")
        rail.setFixedWidth(64)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(8, 24, 8, 16)
        rl.setSpacing(8)

        _ICONS = [("⊞", 0), ("⊕", 1), ("≡", 2), ("⚙", 3)]
        btns = []
        for icon, idx in _ICONS:
            b = QPushButton(icon)
            b.setFixedSize(48, 48)
            b.setObjectName("NavBtn")
            b.setToolTip(["Grid", "Enroll", "Intelligence", "Settings"][idx])
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, i=idx: self.switch_view(i))
            rl.addWidget(b)
            btns.append(b)

        rl.addStretch()
        health = SystemHealthIndicator()
        rl.addWidget(health)
        # Mark first button active at start
        btns[0].setObjectName("NavBtnActive")
        return rail, btns, health

    def _build_intel_panel(self):
        panel = QFrame()
        panel.setObjectName("IntelPanel")
        panel.setFixedWidth(0)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)

        hdr = QLabel("TACTICAL INTELLIGENCE")
        hdr.setObjectName("IntelHeader")
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        cont = QWidget()
        list_lay = QVBoxLayout(cont)
        list_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        list_lay.setSpacing(12)
        list_lay.setContentsMargins(12, 16, 12, 16)
        scroll.setWidget(cont)
        pl.addWidget(scroll)

        anim_max = QPropertyAnimation(panel, b"maximumWidth")
        anim_max.setDuration(280)
        anim_max.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim_min = QPropertyAnimation(panel, b"minimumWidth")
        anim_min.setDuration(280)
        anim_min.setEasingCurve(QEasingCurve.Type.InOutQuad)

        return panel, list_lay, anim_max, anim_min

    # ------------------------------------------------------------------
    # Timer setup
    # ------------------------------------------------------------------

    def _start_timers(self):
        clock_t = QTimer(self)
        clock_t.timeout.connect(self._tick_clock)
        clock_t.start(1000)
        self._tick_clock()

        poll_t = QTimer(self)
        poll_t.timeout.connect(self.check_for_new_streams)
        poll_t.start(POLL_INTERVAL_MS)

        alert_t = QTimer(self)
        alert_t.timeout.connect(self.check_for_alerts)
        alert_t.start(ALERT_INTERVAL_MS)

        cleanup_t = QTimer(self)
        cleanup_t.timeout.connect(self.cleanup_intel_panel)
        cleanup_t.start(CLEANUP_INTERVAL_MS)

        health_t = QTimer(self)
        health_t.timeout.connect(self.check_system_health)
        health_t.start(HEALTH_INTERVAL_MS)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def switch_view(self, index: int):
        _titles = {
            0: "GOD'S EYE GRID",
            1: "WATCHDOG ENROLLMENT",
            2: "CENTRAL INTELLIGENCE",
            3: "SYSTEM SETTINGS",
        }
        self.stacked.setCurrentIndex(index)
        self.page_title_lbl.setText(_titles.get(index, ""))

        if index != 0 and self.intel_panel.width() > 0:
            self.toggle_intel_panel(False)
        elif index == 0 and self.active_intel_cards:
            self.toggle_intel_panel(True)

        btns = [self.btn_cameras, self.btn_watchdog, self.btn_reports, self.btn_settings]
        for i, btn in enumerate(btns):
            btn.setObjectName("NavBtnActive" if i == index else "NavBtn")
        self.apply_styles()

        if index == 2:
            self.ci_view.load()

    # ------------------------------------------------------------------
    # Intel panel
    # ------------------------------------------------------------------

    def toggle_intel_panel(self, show: bool):
        target = INTEL_PANEL_WIDTH if show else 0
        for anim in (self.intel_animation, self.intel_min_anim):
            anim.stop()
            anim.setEndValue(target)
            anim.start()

    # ------------------------------------------------------------------
    # Stream session management
    # ------------------------------------------------------------------

    def check_for_new_streams(self):
        while new_stream_signals:
            cid = new_stream_signals.popleft()
            if cid not in self.active_sessions:
                self._start_session(cid)

    def _start_session(self, client_id: str):
        card = CameraCard(client_id)
        self.grid_view.add_card(card)

        proc = VideoProcessor(client_id)
        proc.frame_ready.connect(
            lambda img, cid=client_id: self._update_stream(cid, img)
        )
        proc.stream_inactive.connect(self._stop_session)
        proc.person_identified.connect(self.handle_detection)
        proc.objects_detected.connect(self.handle_object_detection)

        self.active_sessions[client_id] = {"worker": proc, "card": card}
        watchdog.register_camera_metadata(client_id, ["Airport", "Railway Station"])
        proc.start()
        print(f"UI: Session started → {client_id}")

    def _update_stream(self, client_id: str, qt_img: QImage):
        session = self.active_sessions.get(client_id)
        if session:
            card  = session["card"]
            label = card.video_label
            label.setPixmap(QPixmap.fromImage(qt_img))
            card.update_fps()
            session["worker"].set_target_size(label.width(), label.height())

    def _stop_session(self, client_id: str):
        session = self.active_sessions.pop(client_id, None)
        if session:
            session["worker"].stop()
            self.grid_view.remove_card(session["card"])
        print(f"UI: Session ended → {client_id}")

    # ------------------------------------------------------------------
    # Intel panel detection handler
    # ------------------------------------------------------------------

    def handle_detection(self, metadata: dict):
        aadhar = metadata.get("aadhar")
        if not aadhar:
            return
        self.intel_last_seen[aadhar] = time.time()
        if aadhar not in self.active_intel_cards:
            if not self.active_intel_cards:
                self.toggle_intel_panel(True)
            card = PersonInfoCard(metadata)
            self.active_intel_cards[aadhar] = card
            self.intel_list_layout.insertWidget(0, card)

    def handle_object_detection(self, data: dict):
        client_id = data.get("client_id")
        objects = data.get("objects", [])
        if not objects: return
        
        # 1. Update camera card overlay
        obj_counts = {}
        for o in objects:
            lbl = o['label'].lower()
            obj_counts[lbl] = obj_counts.get(lbl, 0) + 1
        
        counts_str = ", ".join([f"{c} {l}" if c > 1 else l for l, c in obj_counts.items()])
        session = self.active_sessions.get(client_id)
        if session:
            session["card"].update_metadata(f"OBJ: {counts_str.upper()}")

        # 2. Push to Intel Panel
        for label, count in obj_counts.items():
            now = time.time()
            obj_id = f"OBJ_{label.upper()}"
            self.intel_last_seen[obj_id] = now
            if obj_id not in self.active_intel_cards:
                if not self.active_intel_cards:
                    self.toggle_intel_panel(True)
                metadata = {
                    'name': label.upper(),
                    'aadhar': obj_id,
                    'threat_level': 'Low',
                    'source': client_id,
                    'is_object': True,
                    'count': count
                }
                card = PersonInfoCard(metadata)
                self.active_intel_cards[obj_id] = card
                self.intel_list_layout.insertWidget(0, card)
            else:
                 self.active_intel_cards[obj_id].update_count(count)

    def cleanup_intel_panel(self):
        now      = time.time()
        stale    = [a for a, t in self.intel_last_seen.items()
                    if now - t > INTEL_CLEANUP_S]
        for aadhar in stale:
            card = self.active_intel_cards.pop(aadhar, None)
            if card:
                self.intel_list_layout.removeWidget(card)
                card.deleteLater()
            self.intel_last_seen.pop(aadhar, None)
        if not self.active_intel_cards and self.intel_panel.width() > 0:
            self.toggle_intel_panel(False)

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------

    def _tick_clock(self):
        self.clock_lbl.setText(datetime.now().strftime("%H:%M:%S  IST"))

    def check_for_alerts(self):
        msg = self.pubsub.get_message()
        if msg:
            try:
                alert = json.loads(msg["data"].decode("utf-8"))
                if alert.get("type") == "SECURITY_ALERT":
                    self.alert_label.setText(alert["message"])
                    self.alert_banner.show()
            except Exception:
                pass

    def check_system_health(self):
        redis_ok = mongo_ok = False
        try:
            cache.ping(); redis_ok = True
        except Exception as e:
            print(f"Health Check: Redis Error - {e}")
        try:
            from core.database import get_sync_db
            db = get_sync_db()
            if db is not None:
                db.command("ping"); mongo_ok = True
            else:
                print("Health Check: MongoDB handle is None")
        except Exception as e:
            print(f"Health Check: MongoDB Error - {e}")

        self.health_indicator.update_status(redis_ok, mongo_ok)
        ok, err = "#10B981", "#EF4444"
        self.tb_redis.setProperty("status", "online" if redis_ok else "offline")
        self.tb_mongo.setProperty("status", "online" if mongo_ok else "offline")
        
        # Refresh styles
        for lbl in [self.tb_redis, self.tb_mongo]:
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    # ------------------------------------------------------------------
    # Stylesheet
    # ------------------------------------------------------------------

    def apply_styles(self):
        self.setStyleSheet(DASHBOARD_QSS)
