import os
import json
import time
import asyncio
import tempfile
import uuid
import base64
import queue
import urllib.parse
import subprocess
import socket
import logging
import psutil
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import Response
from fastapi.responses import StreamingResponse
from nicegui import ui, app

# Ryuk AI Imports
from core.state import cache, new_stream_signals
from core.database import get_sync_db, init_db
from core.server import app as streaming_app, server as ws_server
from core.watchdog_indexer import (
    get_all_profiles, delete_profile, update_profile, 
    enroll_face, get_activity_report, delete_camera,
    register_camera_metadata, get_profile, finalize_activity_session
)
from core.agent import ryuk_agent
from core.discovery import discover_cameras
from components.processor import Processor
from config import (
    POLL_INTERVAL_MS, ALERT_INTERVAL_MS,
    HEALTH_INTERVAL_MS, SERVER_PORT, INTEL_CLEANUP_S,
    RTSP_URL_TEMPLATE
)

# Modular UI Components
from ui.styles import (
    BG_COLOR, TEXT_HIGH, PRIMARY_COLOR, ERROR_COLOR, SUCCESS_COLOR,
    inject_styles, get_threat_color
)
from ui.nice_components.widgets.camera_card import CameraCard
from ui.nice_components.widgets.intel_panel_item import IntelPanelItem
from ui.nice_components.views.grid_view import GridView
from ui.nice_components.views.enrollment_view import EnrollmentView
from ui.nice_components.views.registry_view import RegistryView
from ui.nice_components.views.system_view import SystemView

# Setup logging
logger = logging.getLogger("ryuk")

# Global state
active_sessions: Dict[str, Processor] = {}

class NiceDashboard:
    def __init__(self, ip_address: str):
        self.ip_address = ip_address
        self.server_port = SERVER_PORT
        self.intel_cards: Dict[str, dict] = {} 
        self.track_identities: Dict[tuple, str] = {} # (client_id, track_id) -> aadhar
        self.intel_last_seen: Dict[str, float] = {} 
        self.intel_is_active: Dict[str, bool] = {} 
        self.profile_refresh_cache: Dict[str, float] = {} # aadhar -> last_db_refresh_time
        self.intel_start_times: Dict[str, float] = {} # aadhar -> session_start_time
        self.intel_elements: Dict[str, IntelPanelItem] = {} 
        
        self.redis_healthy = False
        self.mongo_healthy = False
        self.left_panel_visible = True
        self.right_panel_visible = True
        self.dashboard_id = str(uuid.uuid4())
        
        self.camera_cards: Dict[str, CameraCard] = {}
        self.ui_queue = queue.Queue()
        self.uploaded_image_bytes = None

        self._setup_ui()
        
        # Start background tasks
        self.background_tasks = set()
        ui.timer(2.0, self._update_system_stats)
        ui.timer(2.0, self._check_new_streams)
        ui.timer(1.0, self._update_clock)
        ui.timer(5.0, self._cleanup_intel)
        ui.timer(0.05, self._process_ui_queue)
        
        # Redis subscriber for real-time alerts
        task = asyncio.create_task(self._subscribe_alerts())
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    def _setup_ui(self):
        ui.query('body').style(f'background-color: {BG_COLOR}; color: {TEXT_HIGH}; font-family: "Outfit", sans-serif; overflow: hidden;')
        inject_styles()

        with ui.row().classes('w-full h-screen no-wrap gap-0 relative'):
            # MAIN WORKSPACE
            with ui.column().classes('h-full grow p-0 relative overflow-hidden'):
                # 1. MODERN TOP NAVIGATION
                with ui.row().classes('absolute top-6 left-1/2 -translate-x-1/2 modern-nav items-center gap-2 opacity-40 hover:opacity-100 transition-opacity duration-500 hover:duration-200 group'):
                    # Logo
                    ui.image('/static/logo.png').classes('w-8 h-8 mr-2 logo-glow cursor-pointer').on('click', lambda: self.switch_view(0))
                    
                    self.nav_btns = {}
                    nav_items = {
                        0: ("CAMERAS", "grid_view"),
                        1: ("ENROLL", "person_add"),
                        2: ("REGISTRY", "badge"),
                        3: ("CONFIG", "settings"),
                        4: ("SYSTEM", "dns")
                    }
                    
                    for i, (label, icon) in nav_items.items():
                        btn = ui.button(label, on_click=lambda i=i: self.switch_view(i)).classes('nav-pill')
                        btn.props(f'icon={icon} flat color=white')
                        if i == 0: btn.classes('active')
                        self.nav_btns[i] = btn

                # 2. MAIN VIEW CONTAINER
                with ui.column().classes('w-full h-full p-4 pt-20'):
                    with ui.tabs().classes('hidden') as self.tabs:
                        ui.tab('cameras')
                        ui.tab('enroll')
                        ui.tab('registry')
                        ui.tab('config')
                        ui.tab('system')

                    with ui.tab_panels(self.tabs, value='cameras').classes('w-full grow bg-transparent').style('height: calc(100vh - 120px)'):
                        self.grid_view = GridView(self._on_add_camera, self._on_fullscreen, self._on_delete_camera)
                        # grid_view.create_add_card() call moved to _load_initial_state
                        self.enroll_view = EnrollmentView(on_upload=self._on_enroll_upload, on_submit=self._on_enroll_submit)
                        self.registry_view = RegistryView(on_search=self._on_registry_search)
                        self.registry_view.set_callbacks(
                            on_logs=self._show_activity_tracking,
                            on_edit=self._on_registry_edit,
                            on_delete=self._on_registry_delete_confirm,
                        )
                        
                        with ui.tab_panel('config').classes('p-12'):
                            with ui.column().classes('gap-4'):
                                ui.label("SYSTEM OVERRIDES").classes('text-2xl font-black glow-text mb-4')
                                with ui.row().classes('gap-8'):
                                    with ui.column().classes('gap-2'):
                                        ui.label("AI ENGINE").classes('text-[10px] font-bold opacity-30')
                                        ui.switch('FACE RECOGNITION', value=True).props('dark')
                                        ui.switch('THREAT DETECTION', value=True).props('dark')
                                    with ui.column().classes('gap-2'):
                                        ui.label("THRESHOLDS").classes('text-[10px] font-bold opacity-30')
                                        ui.slider(min=0.5, max=0.99, value=0.85, step=0.01).props('dark label-always label-value="{value}"').classes('w-48')
                                        ui.label("Confidence Floor").classes('text-[10px] opacity-50')
                        
                        self.system_view = SystemView(SERVER_PORT, self.ip_address)

            # 3. SIDE PANELS
            # Intel Panel (Right)
            with ui.column().classes('h-full w-80 telemetry-bar p-4 gap-4 transition-all duration-500 border-l border-white/10') as self.intel_panel:
                ui.label("LIVE INTELLIGENCE").classes('text-xs font-black tracking-[3px] text-primary/80 mb-2')
                self.intel_scroll = ui.scroll_area().classes('grow w-full scroll-hidden')
                with self.intel_scroll:
                    self.intel_container = ui.column().classes('w-full gap-2')

        # Control panel toggle buttons (absolute positioned)
        ui.button(on_click=lambda: self.toggle_panel('intel')).props('icon=chevron_right flat').classes('absolute right-2 top-1/2 -translate-y-1/2 opacity-20 hover:opacity-100 z-10')
        
        # Trigger initial data load
        ui.timer(1.0, self._load_initial_state, once=True)
        # Live system stats refresh (every 3s)
        ui.timer(3.0, self._update_system_stats)


    def _update_system_stats(self):
        sv = self.system_view
        if not sv: return

        # ── GPU Utilization (NVIDIA) ─────────────────────────────────
        try:
            import pynvml
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            
            # Model Name
            gpu_name = pynvml.nvmlDeviceGetName(handle)
            if hasattr(sv, 'sys_gpu_name'): sv.sys_gpu_name.set_text(gpu_name)
            
            # Usage metrics
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            gpu_util = util.gpu
            if hasattr(sv, 'sys_gpu_util_pct'): sv.sys_gpu_util_pct.set_text(f'{gpu_util}%')
            if hasattr(sv, 'sys_gpu_bar'): sv.sys_gpu_bar.set_value(gpu_util / 100)
            
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            vram_used = mem.used // (1024**2)
            vram_total = mem.total // (1024**2)
            vram_pct = vram_used / vram_total if vram_total else 0
            if hasattr(sv, 'sys_vram_usage'): sv.sys_vram_usage.set_text(f'{vram_used}MB / {vram_total}MB')
            if hasattr(sv, 'sys_vram_pct_lbl'): sv.sys_vram_pct_lbl.set_text(f'{int(vram_pct*100)}%')
            if hasattr(sv, 'sys_vram_bar'): sv.sys_vram_bar.set_value(vram_pct)
            
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            if hasattr(sv, 'sys_gpu_temp'): sv.sys_gpu_temp.set_text(f'{temp}°C')

            # GPU Processes
            procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
            if hasattr(sv, 'gpu_process_container'):
                sv.gpu_process_container.clear()
                if not procs:
                    with sv.gpu_process_container:
                        ui.label("No active GPU processes detected.").classes('text-[13px] opacity-20 italic py-4')
                else:
                    for p in procs:
                        try:
                            proc_info = psutil.Process(p.pid)
                            with ui.row().classes('w-full items-center gap-4 p-2 border-b border-white/5').move(sv.gpu_process_container):
                                ui.label(str(p.pid)).classes('text-[10px] font-mono opacity-40 w-12')
                                ui.label(proc_info.name()).classes('text-[12px] font-bold grow')
                                ui.label(f"{p.usedGpuMemory // (1024**2)} MB").classes('text-[11px] font-mono text-purple-300')
                        except: continue
            
            pynvml.nvmlShutdown()
        except:
            if hasattr(sv, 'sys_gpu_name'): sv.sys_gpu_name.set_text("N/A")

        # ── Network & Latency ────────────────────────────────────────
        try:
            t1 = time.time()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                try:
                    s.connect(("127.0.0.1", self.server_port))
                    ping = (time.time() - t1) * 1000
                    if hasattr(sv, 'sys_ping'): sv.sys_ping.set_text(f'{ping:.1f} ms')
                except: pass

            net = psutil.net_io_counters()
            sent_mb = net.bytes_sent / (1024**2)
            recv_mb = net.bytes_recv / (1024**2)
            if hasattr(sv, 'sys_net_up'): sv.sys_net_up.set_text(f'{sent_mb:.1f} MB')
            if hasattr(sv, 'sys_net_down'): sv.sys_net_down.set_text(f'{recv_mb:.1f} MB')
        except: pass

        # ── WebSocket & Stream Stats ─────────────────────────────────
        try:
            cam_count = len(active_sessions)
            if hasattr(sv, 'ws_active_streams'): sv.ws_active_streams.set_text(str(cam_count))
            if hasattr(sv, 'ws_subscribers'):
                total_subs = len(ws_server._alert_clients) if hasattr(ws_server, '_alert_clients') else 0
                sv.ws_subscribers.set_text(str(total_subs))
        except: pass

        # ── Service health ───────────────────────────────────────────
        try:
            # Check for core processes
            engine_proc = None
            sink_proc = None
            mongo_ok = False
            redis_ok = False
            
            try:
                db = get_sync_db()
                if db is not None:
                    db.command('ping')
                    mongo_ok = True
            except Exception as e:
                # Still log but it should work now
                pass

            try:
                cache.ping()
                redis_ok = True
            except: pass

            # Global Metrics
            total_procs = 0
            total_threads = 0
            for p in psutil.process_iter(['cmdline', 'num_threads']):
                try:
                    total_procs += 1
                    total_threads += p.info.get('num_threads', 0)
                    cmd = p.info.get('cmdline')
                    if cmd:
                        if any('services/unified_engine.py' in arg for arg in cmd): engine_proc = p
                        if any('services/sink.py' in arg for arg in cmd): sink_proc = p
                except: continue

            from ui.styles import SUCCESS_COLOR, ERROR_COLOR
            # Update Global counts
            if hasattr(sv, 'sys_total_procs'): sv.sys_total_procs.set_text(str(total_procs))
            if hasattr(sv, 'sys_total_threads'): sv.sys_total_threads.set_text(str(total_threads))
            try:
                lavg = os.getloadavg()
                if hasattr(sv, 'sys_load_avg'): sv.sys_load_avg.set_text(f"{lavg[0]:.2f}, {lavg[1]:.2f}, {lavg[2]:.2f}")
            except: pass

            # Update AI Engine Status
            if hasattr(sv, 'svc_engine_status'):
                status = "ONLINE" if engine_proc else "OFFLINE"
                sv.svc_engine_status.set_text(status)
                sv.svc_engine_status.style(f"color: {SUCCESS_COLOR if status == 'ONLINE' else ERROR_COLOR}")
                if engine_proc:
                    try:
                        cpu = engine_proc.cpu_percent()
                        mem = engine_proc.memory_info().rss / (1024 * 1024)
                        sv.svc_engine_metrics.set_text(f"{cpu:.1f}% CPU • {mem:.0f}MB")
                    except: pass

            # Update Sink Status
            if hasattr(sv, 'svc_sink_status'):
                status = "ONLINE" if sink_proc else "OFFLINE"
                if sink_proc and not mongo_ok: status = "DEGRADED"
                sv.svc_sink_status.set_text(status)
                sv.svc_sink_status.style(f"color: {SUCCESS_COLOR if status == 'ONLINE' else ('#f59e0b' if status == 'DEGRADED' else ERROR_COLOR)}")
                if sink_proc:
                    try:
                        cpu = sink_proc.cpu_percent()
                        mem = sink_proc.memory_info().rss / (1024 * 1024)
                        sv.svc_sink_metrics.set_text(f"{cpu:.1f}% CPU • {mem:.0f}MB")
                    except: pass

            # Database Icons
            if hasattr(sv, 'db_mongo_status'):
                sv.db_mongo_status.props(f"color={'green' if mongo_ok else 'red'}")
            if hasattr(sv, 'db_redis_status'):
                sv.db_redis_status.props(f"color={'green' if redis_ok else 'red'}")

        except Exception as e:
            print(f"DEBUG: Health Polling Error: {e}")
        
        # ── Camera Cards Status ──────────────────────────────────────
        try:
            for cid, card in self.camera_cards.items():
                is_active = cid in active_sessions
                card.update_stream(is_active)
        except: pass


    def switch_view(self, idx: int):

        views = {0: 'cameras', 1: 'enroll', 2: 'registry', 3: 'config', 4: 'system'}
        self.tabs.value = views[idx]
        for i, btn in self.nav_btns.items():
            if i == idx: btn.classes('active')
            else: btn.classes(remove='active')

    def toggle_panel(self, panel_type: str):
        if panel_type == 'intel':
            self.right_panel_visible = not self.right_panel_visible
            self.intel_panel.set_visibility(self.right_panel_visible)


    async def _check_new_streams(self):
        while new_stream_signals:
            cid = new_stream_signals.popleft()
            if cid not in active_sessions:
                print(f"DEBUG: Starting session for {cid}")
                proc = Processor(cid)
                active_sessions[cid] = proc
                proc.start()
                
                # Update UI
                self.ui_queue.put(lambda c=cid: self._add_camera_to_ui(c))

    def _load_initial_state(self):
        """Fetch existing cameras and profiles from DB."""
        # 1. Load Cameras
        # 1. Load Cameras
        try:
            db = get_sync_db()
            if db is not None:
                cameras = list(db.cameras.find({}))
                for cam in cameras:
                    cid = cam.get('client_id')
                    url = cam.get('source')
                    if cid:
                        self.ui_queue.put(lambda c=cid, u=url: self._add_camera_to_ui(c, u))
        except Exception as e:
            print(f"DEBUG: Error loading cameras: {e}")

        # 2. Load Profiles
        self._refresh_registry()
        
        # 3. Finally add the "Add Camera" button (at the end)
        self.ui_queue.put(lambda: self.grid_view.create_add_card())

    def _refresh_registry(self):
        """Reload the identity registry view."""
        try:
            profiles = get_all_profiles()
            # Queue all UI updates to ensure they run in the correct NiceGUI context
            def _do_refresh():
                try:
                    self.registry_view.clear()
                    for profile in profiles:
                        self.registry_view.add_profile(profile)
                except Exception as e:
                    print(f"DEBUG: Registry render error: {e}")
            self.ui_queue.put(_do_refresh)
        except Exception as e:
            print(f"DEBUG: Error refreshing registry: {e}")


    def _on_registry_search(self, e):
        """Filter the registry view based on search query."""
        query = e.value.lower()
        try:
            db = get_sync_db()
            if db is not None:
                # Search by name, aadhar, phone, or address
                filter_obj = {
                    "$or": [
                        {"name": {"$regex": query, "$options": "i"}},
                        {"aadhar": {"$regex": query, "$options": "i"}},
                        {"phone": {"$regex": query, "$options": "i"}},
                        {"address": {"$regex": query, "$options": "i"}}
                    ]
                }
                profiles = list(db.profiles.find(filter_obj))
                self.registry_view.clear()
                for profile in profiles:
                    self.registry_view.add_profile(profile)
        except Exception as e:
            ui.notify(f"Search failed: {e}", type='negative')

    def _add_camera_to_ui(self, client_id, url=None):
        if client_id not in self.camera_cards:
            # Persistent check for saved source if not provided
            if not url:
                try:
                    db = get_sync_db()
                    if db is not None:
                        cam = db.cameras.find_one({"client_id": client_id})
                        if cam: url = cam.get('source')
                except: pass

            # Enable session if url is available
            if url and client_id not in active_sessions:
                from components.processor import Processor
                proc = Processor(client_id, source_url=url)
                active_sessions[client_id] = proc
                proc.add_listener(self)
                proc.start()
                logger.info(f"UI: Initialized session for {client_id} -> {url}")

            card = self.grid_view.add_camera(client_id)
            self.camera_cards[client_id] = card
            card.update_stream(True)


    def _update_clock(self):
        # Could update a clock element if one existed in modern-nav
        pass

    async def _cleanup_intel(self):
        now = time.time()
        to_remove = []
        for aadhar, last_seen in self.intel_last_seen.items():
            if now - last_seen > INTEL_CLEANUP_S:
                to_remove.append(aadhar)
        
        for aadhar in to_remove:
            if aadhar in self.intel_elements:
                # 1. Finalize the duration before cleaning up
                start_time = self.intel_start_times.get(aadhar)
                if start_time:
                    duration = now - start_time
                    # Get the source from the last detection if possible
                    # Since we're in the UI, we can call the indexer directly
                    # If we don't know the exact client_id, the indexer will find the most recent
                    # but let's try to be accurate.
                    last_source = "Unknown"
                    if aadhar in self.intel_cards:
                        last_source = self.intel_cards[aadhar].get('source', 'Unknown')
                    
                    import core.watchdog_indexer as watchdog
                    watchdog.finalize_activity_session(aadhar, last_source, duration)

                self.intel_elements[aadhar].delete()
                del self.intel_elements[aadhar]
            if aadhar in self.intel_last_seen: del self.intel_last_seen[aadhar]
            if aadhar in self.intel_is_active: del self.intel_is_active[aadhar]
            if aadhar in self.intel_start_times: del self.intel_start_times[aadhar]

    def _dispatch_notification(self, data: dict):
        """Unified point for all system notifications."""
        msg_type = data.get('type', 'INTEL_UPDATE')
        name = data.get('name', 'Unknown Subject')
        source = data.get('source', 'Unknown Camera').replace('_', ' ').title()
        threat_lv = data.get('threat_level', 'Low').upper()
        
        if msg_type == "SECURITY_ALERT":
            # ONLY show popups for High/Critical threat levels
            if threat_lv not in ['HIGH', 'CRITICAL']:
                return 
            
            # Tactical Alert: Higher severity
            notice_type = 'negative'
            self.ui_queue.put(lambda n=name, s=source, t=threat_lv, v=notice_type: ui.notify(
                f"<b>ENTRY DETECTED: {n}</b>",
                caption=f"LOCATION: {s} | PRIORITY: {t}",
                type=v,
                icon='security',
                html=True,
                actions=[{'icon': 'close', 'color': 'white'}],
                timeout=0, # Persistent for security
                position='top-right'
            ))
        else:
            # Standard Intelligence Update: Lower severity
            self.ui_queue.put(lambda n=name, s=source: ui.notify(
                f"<b>INTEL: {n}</b>",
                caption=f"SIGHTING AT {s}",
                color=PRIMARY_COLOR,
                icon='info_outline',
                html=True,
                actions=[{'icon': 'close', 'color': 'white'}],
                timeout=4,
                position='top-right'
            ))

    async def _subscribe_alerts(self):
        try:
            pubsub = cache.pubsub()
            pubsub.subscribe('security_alerts')
            while not app.is_stopping:
                msg = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0)
                if msg:
                    data = json.loads(msg['data'])
                    # 1. Update the sidebar Intel panel
                    self.ui_queue.put(lambda d=data: self._update_intel(d))
                    # 2. Dispatch a browser notification
                    self._dispatch_notification(data)
                    
        except Exception as e:
            print(f"DEBUG: Alert subscriber error: {e}")

    def _update_intel(self, metadata: dict):
        aadhar = metadata.get('aadhar')
        if not aadhar: return
        
        now = time.time()
        
        # Sync last seen & start time
        self.intel_last_seen[aadhar] = now
        if aadhar not in self.intel_start_times:
            self.intel_start_times[aadhar] = now
        
        # Save last known metadata for cleanup reference
        self.intel_cards[aadhar] = metadata
        
        # REAL-TIME SYNC: Refresh identity metadata (name, threat) from DB every 5s
        last_refresh = self.profile_refresh_cache.get(aadhar, 0)
        if now - last_refresh > 5.0:
            try:
                profile = get_profile(aadhar)
                if profile:
                    # Merge DB truth into the detection metadata
                    metadata['name'] = profile.get('name', metadata.get('name', 'Unknown'))
                    metadata['threat_level'] = profile.get('threat_level', metadata.get('threat_level', 'Low'))
                    self.profile_refresh_cache[aadhar] = now
            except Exception as e:
                logger.error(f"UI: Profile sync failed for {aadhar} — {e}")
        
        if aadhar not in self.intel_elements:
            with self.intel_container:
                item = IntelPanelItem(metadata).on('click', lambda a=aadhar: self._show_activity_tracking(a))
                self.intel_elements[aadhar] = item
        else:
            # Fully sync the card (including threat level and name)
            self.intel_elements[aadhar].update_metadata(metadata)

    def _show_activity_tracking(self, aadhar: str):
        profile = get_profile(aadhar) or {}
        subject_name = profile.get('name', aadhar).title()
        logs = get_activity_report(aadhar, limit=30)

        with ui.dialog().classes('overflow-hidden') as dialog, ui.card().classes('p-0 cyber-panel min-w-[500px] h-[700px] flex-nowrap overflow-hidden'):
            with ui.column().classes('w-full h-full gap-0'):
                # Header
                with ui.row().classes('w-full px-6 py-5 items-center justify-between border-b border-white/10 bg-white/5'):
                    with ui.column().classes('gap-0'):
                        ui.label('SURVEILLANCE HISTORY').classes('text-[10px] font-black tracking-[4px] text-primary/60')
                        ui.label(f"{subject_name.upper()}").classes('text-xl font-black text-white')
                    ui.button(icon='close', on_click=dialog.close).props('flat round color=white/30')

                # Timeline Content
                with ui.scroll_area().classes('grow w-full p-8 scroll-hidden'):
                    if not logs:
                        with ui.column().classes('absolute-center items-center py-20 gap-4 opacity-20'):
                            ui.icon('history', size='64px')
                            ui.label('No movements recorded in the current epoch.').classes('text-xs font-black tracking-[2px]')
                    else:
                        with ui.column().classes('w-full gap-0 relative'):
                            # The Vertical Spine
                            ui.element('div').classes('absolute left-[33px] top-4 bottom-4 w-px bg-white/10')
                            
                            for i, log in enumerate(logs):
                                ts = log.get('timestamp')
                                if not ts: continue
                                
                                # Requested Format: 2025 April 23
                                # Note: Python's %B is locale-aware, using strftime
                                date_val = ts.strftime("%Y %B %d")
                                time_val = ts.strftime("%H:%M")
                                
                                # Format duration
                                duration_val = log.get('duration')
                                duration_str = None
                                is_live = False
                                
                                # LIVE OVERRIDE: If person is currently in frame, show live timer
                                if i == 0 and aadhar in self.intel_start_times:
                                    duration_val = time.time() - self.intel_start_times[aadhar]
                                    is_live = True

                                if duration_val:
                                    d_min = int(duration_val // 60)
                                    d_sec = int(duration_val % 60)
                                    duration_str = f"{d_min:02d}:{d_sec:02d}"
                                    if is_live: duration_str += " LIVE"
                                
                                # Use simple names for cameras
                                camera_id = log.get('client_id', 'Unknown Device')
                                camera_name = camera_id.replace('_', ' ').replace('-', ' ').title()
                                
                                with ui.row().classes('w-full no-wrap mb-8 items-start'):
                                    # Left side: Timestamp
                                    ui.label(time_val).classes('w-8 text-[11px] font-mono text-white/40 mt-1 shrink-0 text-right mr-4')
                                    
                                    # Middle: Indicator Node
                                    with ui.element('div').classes('relative w-[15px] shrink-0 mt-[6px]'):
                                        if i == 0:
                                            # Pulsating node for latest event
                                            ui.element('div').classes('absolute -inset-1 rounded-full bg-primary/40 animate-pulse')
                                            ui.element('div').classes('relative w-3.5 h-3.5 rounded-full bg-primary border-2 border-black')
                                        else:
                                            ui.element('div').classes('relative w-3.5 h-3.5 rounded-full bg-white/10 border-2 border-black')
                                    
                                    # Right side: Detail
                                    with ui.column().classes('pl-4 gap-1'):
                                        # Phrasing requested: "Name was at cameraname at time"
                                        text = f"{subject_name} was detected at"
                                        with ui.row().classes('items-center gap-1'):
                                            ui.label(text).classes('text-[12px] opacity-60 font-medium')
                                            ui.label(camera_name).classes('text-[13px] font-black text-white px-2 py-0.5 bg-white/5 rounded-sm')
                                        
                                        with ui.column().classes('gap-1.5 mt-1'):
                                            # Date Row
                                            with ui.row().classes('items-center gap-1.5 opacity-30'):
                                                ui.icon('calendar_today', size='12px')
                                                ui.label(date_val).classes('text-[10px] uppercase tracking-wider font-bold')
                                            
                                            # Duration Row (Below Date)
                                            if duration_str:
                                                pulse_cls = 'animate-pulse' if is_live else ''
                                                with ui.row().classes(f'items-center gap-1.5 bg-primary/10 px-2 py-0.5 rounded-full border border-primary/20 w-fit {pulse_cls}'):
                                                    ui.icon('timer', size='12px', color='primary')
                                                    ui.label("STAY").classes('text-[8px] font-black text-primary opacity-60 uppercase tracking-widest')
                                                    ui.label(duration_str).classes('text-[10px] font-mono font-bold text-primary')

                                        if log.get('confidence'):
                                            ui.label(f"· ID {log['confidence']*100:.0f}%").classes('text-[10px] font-mono opacity-20 ml-auto absolute bottom-4 right-4')

        dialog.open()


    async def _generate_intel_dossier(self, aadhar: str, container: ui.markdown):
        container.set_content("Initializing core reasoning models...")
        profile = get_profile(aadhar) or {"name": "Unknown", "aadhar": aadhar}
        logs = get_activity_report(aadhar, limit=100)
        
        full_text = ""
        async for chunk in asyncio.to_thread(lambda: ryuk_agent.generate_dossier_stream(profile, logs, "LAST 24 HOURS")):
            # Note: generate_dossier_stream is a generator, we wrap it in to_thread if it's blocking
            # But wait, it's a generator. NiceGUI handles async loops.
            # However, RyukAgent.generate_dossier_stream is synchronous generator (yield).
            # I should iterate in thread or make it async.
            pass
        
        # Let's fix the iteration for synchronous generator in async context
        def iterate():
            nonlocal full_text
            for chunk in ryuk_agent.generate_dossier_stream(profile, logs, "LAST 24 HOURS"):
                full_text += chunk
                container.set_content(full_text)
        
        await asyncio.to_thread(iterate)

    def _process_ui_queue(self):
        while not self.ui_queue.empty():
            try:
                callback = self.ui_queue.get_nowait()
                callback()
            except: break

    def on_detection(self, data: dict):
        """Callback from Processor when faces are identified."""
        client_id = data.get('client_id')
        detections = data.get('detections', [])
        
        # 1. Update identifying information & Persistence
        for det in detections:
            track_id = det.get('track_id')
            aadhar = det.get('aadhar')
            name = det.get('name', 'Unknown')
            
            # TRACK PERSISTENCE: If we identify someone, remember their track
            if track_id is not None and aadhar and name != 'Unknown':
                self.track_identities[(client_id, track_id)] = aadhar
            
            # If current frame is Unknown but we have a saved identity for this track
            if track_id is not None and name == 'Unknown':
                saved_aadhar = self.track_identities.get((client_id, track_id))
                if saved_aadhar:
                    # Update metadata so _update_intel keeps the card alive
                    det['aadhar'] = saved_aadhar
                    # We could also keep the name, but _update_intel 
                    # mainly needs the aadhar to refresh the timer.
            
            # 2. Update camera card overlay text
            if client_id in self.camera_cards and name != 'Unknown':
                text = f"DET: {name}"
                self.ui_queue.put(lambda c=self.camera_cards[client_id], t=text: c.update_metadata(t))

            # 3. Push identified person to the LIVE INTELLIGENCE panel
            if det.get('aadhar') and det.get('name', 'Unknown') != 'Unknown':
                # Enrich with source camera
                enriched = {**det, 'source': client_id}
                self.ui_queue.put(lambda d=enriched: self._update_intel(d))


    def on_stream_start(self, client_id: str):
        if client_id in self.camera_cards:
            self.ui_queue.put(lambda: self.camera_cards[client_id].update_stream(True))

    def on_inactive(self, client_id: str):
        if client_id in self.camera_cards:
            self.ui_queue.put(lambda: self.camera_cards[client_id].update_stream(False))

    def _on_add_camera(self):
        with ui.dialog().classes('w-full') as dialog, ui.card().classes('w-full max-w-2xl p-8 cyber-panel relative overflow-hidden'):
            ui.element('div').classes('scanline opacity-10')
            ui.label('LINK NEW SENSOR').classes('text-sm font-black tracking-[6px] text-primary/90 mb-2')
            
            # Auto-populated state based on selection
            self.selected_node_info = {"ip": None, "port": None}

            async def run_discovery():
                status.set_text('SCANNING NETWORK...')
                status.classes(add='animate-pulse')
                try:
                    results = await discover_cameras()
                    status.set_text(f'FOUND {len(results)} POTENTIAL NODES')
                    status.classes(remove='animate-pulse')
                    results_div.clear()
                    
                    if not results:
                        with results_div:
                            ui.label('No active nodes detected. Retry?').classes('text-white/20 italic text-xs py-2')
                        return
                    
                    for res in results:
                        ip = res['ip']
                        port = res['ports'][0] if res['ports'] else '554'
                        with results_div:
                            with ui.row().classes('w-full items-center justify-between p-4 border border-white/5 hover:border-primary/40 transition-all rounded bg-white/5 group cursor-pointer') as r_item:
                                def on_row_click(i=ip, p=port):
                                    self.selected_node_info = {"ip": i, "port": p}
                                    ui.notify(f"Node {i} selected.")
                                    # Highlight selected
                                    for child in results_div.default_slot.children:
                                        child.classes(remove='border-primary/40 bg-primary/5', add='border-white/5 bg-white/5')
                                    r_item.classes(remove='border-white/5 bg-white/5', add='border-primary/40 bg-primary/5')
                                
                                r_item.on('click', on_row_click)
                                with ui.column().classes('gap-0'):
                                    ui.label(ip).classes('font-black text-sm group-hover:text-primary transition-colors')
                                    ui.label(f"PORT {port} | {res['type'].upper()}").classes('text-[10px] opacity-30 font-mono uppercase')
                                ui.icon('radio_button_checked', color='primary').classes('opacity-10 group-hover:opacity-100 transition-opacity')

                except Exception as ex:
                    status.set_text(f'SCAN ERROR: {ex}')
                    logger.error(f"Discovery Error: {ex}")

            with ui.column().classes('w-full gap-6'):
                # 1. SCAN RESULTS
                with ui.column().classes('w-full gap-2'):
                    with ui.row().classes('w-full items-center justify-between'):
                        status = ui.label('Initializing signal scan...').classes('text-[10px] font-bold tracking-widest text-primary/40 uppercase animate-pulse')
                        ui.button(icon='refresh', on_click=run_discovery).props('flat round dense')
                    results_div = ui.column().classes('w-full max-h-60 overflow-y-auto gap-2 scroll-hidden')

                ui.separator().classes('bg-white/5')

                # 2. CAMERA DETAILS
                with ui.column().classes('w-full gap-4'):
                    name_input = ui.input('CAMERA NAME').classes('w-full').props('dense dark placeholder="e.g. Front Door, Parking Lot"')
                    with ui.row().classes('w-full gap-4'):
                        user_input = ui.input('USERNAME').classes('flex-1').props('dense dark placeholder="admin"')
                        pass_input = ui.input('PASSWORD').classes('flex-1').props('dense dark placeholder="password" password')
                        user_input.value = "admin"
                        pass_input.value = "PASS"

                def proceed_link():
                    ip = self.selected_node_info.get("ip")
                    port = self.selected_node_info.get("port")
                    if not ip:
                        ui.notify("Select a node from the scan results first.", type='warning')
                        return
                    
                    user = user_input.value or "admin"
                    pwd = pass_input.value or "PASS"
                    
                    # Generate unique CID based on name or fallback to IP
                    raw_name = name_input.value.strip() if name_input.value else ""
                    if raw_name:
                        # Sanitize name: alphanumeric and underscores only
                        import re
                        cid = re.sub(r'[^a-zA-Z0-9]', '_', raw_name).upper()
                    else:
                        cid = f"CAM-{ip.split('.')[-1]}"
                    
                    try:
                        url = RTSP_URL_TEMPLATE.format(username=user, password=pwd, ip=ip, port=port)
                    except:
                        url = f"rtsp://{user}:{pwd}@{ip}:{port}/"
                    
                    self._link_camera(cid, url, dialog)

                ui.button('ADD CAMERA', on_click=proceed_link).classes('w-full py-4 cyber-btn mt-2').props('unelevated')
            
            # Auto-run discovery on open
            ui.timer(0.1, run_discovery, once=True)
            
            ui.button('CLOSE', on_click=dialog.close).classes('self-center opacity-30 hover:opacity-100 text-[10px] font-black tracking-widest mt-4').props('flat')
        dialog.open()

    def _link_camera(self, cid: str, url: str, dialog):
        if not cid or not url:
            ui.notify("Missing ID or URL", type='warning')
            return
            
        try:
            # 1. Persistence (Include the RTSP URL)
            register_camera_metadata(cid, ["Manual"], url)
            
            # 2. Immediate Initialization
            from components.processor import Processor
            if cid in active_sessions:
                active_sessions[cid].stop()
                
            proc = Processor(cid, source_url=url)
            active_sessions[cid] = proc
            proc.add_listener(self)
            proc.start()
            
            # 3. UI Update
            card = self.grid_view.add_camera(cid)
            card.update_stream(True)
            
            dialog.close()
            ui.notify(f"Camera linked: {cid}", type='positive')
            logger.info(f"UI: Manually linked camera {cid} -> {url}")
        except Exception as e:
            ui.notify(f"Link failed: {e}", type='negative')
            logger.error(f"Link Error: {e}")

    def _on_fullscreen(self, client_id: str):
        with ui.dialog().classes('w-full h-full') as dialog:
            dialog.props('maximized')
            with ui.card().classes('w-full h-full p-0 bg-black items-center justify-center relative overflow-hidden'):
                encoded_cid = urllib.parse.quote(client_id)
                ui.interactive_image(f"/stream/{encoded_cid}").classes('h-full')
                ui.button(icon='close', on_click=dialog.close).props('flat round color=white').classes('absolute top-4 right-4 z-50 bg-black/20')
                ui.label(f"TACTICAL FEED: {client_id}").classes('absolute top-4 left-4 font-black tracking-[4px] opacity-20 text-[10px]')
        dialog.open()

    def _on_delete_camera(self, client_id: str):
        with ui.dialog() as dialog, ui.card().classes('p-6 cyber-panel'):
            ui.label('CONFIRM DELETION').classes('text-xs font-black tracking-[4px] text-red-500 mb-4')
            ui.label(f"Purge all records for node {client_id}?").classes('text-[12px] opacity-70 mb-6')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('CANCEL', on_click=dialog.close).props('flat')
                ui.button('PURGE', on_click=lambda: (
                    ui.notify(f"Node purged: {client_id}", type='warning'),
                    delete_camera(client_id), 
                    active_sessions[client_id].stop() if client_id in active_sessions else None,
                    active_sessions.pop(client_id, None),
                    self.grid_view.remove_camera(client_id), # Ensure UI is updated
                    dialog.close()
                )).props('flat color=red')
        dialog.open()

    def _on_enroll_upload(self, e):
        self.uploaded_image_bytes = e.content.read()
        self.enroll_view.photo_preview.set_source(f'data:image/jpeg;base64,{base64.b64encode(self.uploaded_image_bytes).decode()}')

    def _on_enroll_submit(self):
        data = self.enroll_view.get_data()
        if not data['name'] or not self.uploaded_image_bytes:
            ui.notify("Subject name and biometric data required.", type='warning')
            return
        
        try:
            enroll_face(data['name'], self.uploaded_image_bytes, data)
            ui.notify(f"Subject enrolled: {data['name']}", type='positive')
            self.enroll_view.clear()
            self.uploaded_image_bytes = None
            self._refresh_registry()
        except Exception as ex:
            ui.notify(f"Enrollment failed: {ex}", type='negative')

    def _on_registry_search(self, e):
        query = e.value.lower()
        try:
            profiles = get_all_profiles()
            self.registry_view.clear()
            for profile in profiles:
                if query in profile.get('name', '').lower() or query in profile.get('aadhar', '').lower():
                    self.registry_view.add_profile(profile)
        except Exception as ex:
            print(f"DEBUG: Search error: {ex}")

    def _on_registry_delete_confirm(self, aadhar: str):
        with ui.dialog() as dialog, ui.card().classes('p-6 cyber-panel'):
            ui.label('CONFIRM DELETION').classes('text-xs font-black tracking-[4px] text-red-500 mb-4')
            ui.label(f'Permanently purge subject {aadhar}?').classes('text-[12px] opacity-70 mb-6')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('CANCEL', on_click=dialog.close).props('flat')
                def _do_delete():
                    try:
                        delete_profile(aadhar)
                        ui.notify(f'Subject {aadhar} purged.', type='warning')
                        self._refresh_registry()
                    except Exception as ex:
                        ui.notify(f'Delete failed: {ex}', type='negative')
                    dialog.close()
                ui.button('PURGE', on_click=_do_delete).props('flat color=red')
        dialog.open()

    def _on_registry_edit(self, profile: dict):
        aadhar = profile.get('aadhar', '')
        with ui.dialog() as dialog, ui.card().classes('p-8 cyber-panel min-w-[480px]'):
            ui.label('EDIT SUBJECT').classes('text-xs font-black tracking-[4px] text-primary/80 mb-6')
            name_in  = ui.input('Name',         value=profile.get('name', '')).props('dark standout square').classes('w-full mb-2')
            phone_in = ui.input('Phone',        value=profile.get('phone', '')).props('dark standout square').classes('w-full mb-2')
            addr_in  = ui.input('Address',      value=profile.get('address', '')).props('dark standout square').classes('w-full mb-2')
            thr_in   = ui.select(['Low', 'Medium', 'High'], value=profile.get('threat_level', 'Low'), label='Threat level').props('dark standout square').classes('w-full mb-6')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('CANCEL', on_click=dialog.close).props('flat')
                def _do_save():
                    try:
                        update_profile(aadhar, {
                            'name': name_in.value,
                            'phone': phone_in.value,
                            'address': addr_in.value,
                            'threat_level': thr_in.value,
                        })
                        ui.notify('Profile updated.', type='positive')
                        self._refresh_registry()
                    except Exception as ex:
                        ui.notify(f'Update failed: {ex}', type='negative')
                    dialog.close()
                ui.button('SAVE', on_click=_do_save).props('unelevated color=primary')
        dialog.open()

@ui.page('/')
def main_page():
    # Detect IP for the dashboard instance
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
        s.close()
    except: 
        IP = '127.0.0.1'
    
    NiceDashboard(IP)

app.on_startup(init_db)
app.on_shutdown(lambda: [p.stop() for p in active_sessions.values()])
app.add_static_files('/static', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'))
app.mount('/api', streaming_app)

@app.get('/stream/{client_id:path}')
async def stream_endpoint(client_id: str):
    client_id = urllib.parse.unquote(client_id)
    if client_id not in active_sessions: return Response(status_code=404)
    async def gen():
        last_frame_time = time.time()
        try:
            while not app.is_stopping:
                await asyncio.sleep(0.2) # ~5fps (Optimized per user request)
                if client_id not in active_sessions: break
                
                frame = active_sessions[client_id].latest_processed_frame
                if frame:
                    last_frame_time = time.time()
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                elif time.time() - last_frame_time > 1.0:
                    # Yield a 'CONNECTING' or 'LAG' frame to keep generator alive 
                    # and signal to user that we are waiting for the processor.
                    import cv2
                    import numpy as np
                    placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(placeholder, "CONNECTING...", (100, 240), cv2.FONT_HERSHEY_DUPLEX, 1.5, (0, 140, 255), 2)
                    _, buffer = cv2.imencode('.jpg', placeholder, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                    last_frame_time = time.time() # Reset to avoid spamming
        except asyncio.CancelledError:
            pass # Graceful exit on disconnect or shutdown
        except Exception as e:
            logger.error(f"MJPEG Stream Error: {e}")
        finally:
            print(f"DEBUG: MJPEG Generator — Exiting for {client_id}")

    return StreamingResponse(gen(), media_type='multipart/x-mixed-replace; boundary=frame')
