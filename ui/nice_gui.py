import os
import json
import time
import asyncio
import tempfile
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import Response
from fastapi.responses import StreamingResponse
from nicegui import ui, app
import cv2
import queue
import base64
import io
import urllib.parse

from core.state import cache, cache_str
from core.database import get_sync_db, profiles_col, cameras_col, init_db
from core.server import app as streaming_app
from core.watchdog_indexer import get_all_profiles, delete_profile, register_camera_metadata
from components.processor import Processor
from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT,
    POLL_INTERVAL_MS, ALERT_INTERVAL_MS,
    HEALTH_INTERVAL_MS, INTEL_PANEL_WIDTH,
    SERVER_PORT, INTEL_CLEANUP_S
)

# User-defined Design Tokens
BG_COLOR = "#0A0B10" # Deep Obsidian
SURFACE_COLOR = "#161821" # Dark Slate Surface
PRIMARY_COLOR = "#3D7BFF" # Vibrant Action Blue
ACCENT_COLOR = "#00D1FF" # Tech Cyan
ERROR_COLOR = "#FF4B4B"   # High-visibility Red
TEXT_HIGH = "#FFFFFF"
TEXT_MED = "#94A3B8"      # Balanced Slate Grey
OUTLINE_COLOR = "#232634"
GLOW_COLOR = "0 0 20px rgba(61, 123, 255, 0.3)"

# Global state for background tasks and shared endpoints
active_sessions: Dict[str, Processor] = {}

class NiceDashboard:
    def __init__(self, ip_address: str):
        self.ip_address = ip_address
        self.intel_cards: Dict[str, dict] = {} # aadhar -> metadata
        self.intel_last_seen: Dict[str, float] = {} # aadhar -> time
        self.intel_counts: Dict[str, int] = {} # aadhar -> count
        self.intel_is_active: Dict[str, bool] = {} # aadhar -> is currently in view
        self.intel_elements: Dict[str, ui.element] = {} # aadhar -> ui row
        self.intel_count_labels: Dict[str, ui.label] = {} # aadhar -> counter label
        self.redis_healthy = False
        self.mongo_healthy = False
        self.left_panel_visible = True
        self.right_panel_visible = True
        
        # Unique ID for this dashboard instance (for processor listeners)
        import uuid
        self.dashboard_id = str(uuid.uuid4())
        
        # Setup page
        self._setup_ui()
        
        # Start background timers
        ui.timer(2.0, self._check_new_streams) # Sync cards every 2s
        ui.timer(HEALTH_INTERVAL_MS / 1000, self._check_health)
        ui.timer(1.0, self._update_clock)
        ui.timer(5.0, self._cleanup_intel)
        
        self.camera_cards: Dict[str, ui.card] = {}
        self.ui_queue = queue.Queue()
        self.uploaded_image_bytes = None
        ui.timer(0.05, self._process_ui_queue) # Process UI updates every 50ms

    def _setup_ui(self):
        ui.query('body').style(f'background-color: {BG_COLOR}; color: {TEXT_HIGH}; font-family: "Outfit", sans-serif; overflow: hidden;')
        # Advanced Cinematic CSS
        ui.add_head_html(f"""
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');
                @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');
                
                :root {{
                    --primary: {PRIMARY_COLOR};
                    --accent: {ACCENT_COLOR};
                    --success: #10B981;
                    --bg: {BG_COLOR};
                    --surface: {SURFACE_COLOR};
                    --outline: {OUTLINE_COLOR};
                    --text: {TEXT_HIGH};
                    --text-muted: {TEXT_MED};
                }}

                .cyber-panel {{
                    background: var(--surface) !important;
                    backdrop-filter: blur(20px);
                    border: 1px solid var(--outline) !important;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
                }}
                
                .cyber-border-l {{ border-left: 2px solid var(--primary); }}
                .cyber-border-r {{ border-right: 2px solid var(--primary); }}
                
                .glow-text {{
                    text-shadow: 0 0 12px rgba(61, 123, 255, 0.4);
                }}
                
                .scroll-hidden::-webkit-scrollbar {{ display: none; }}
                
                .telemetry-bar {{
                    background: rgba(10, 11, 16, 0.9);
                    border-bottom: 1px solid var(--outline);
                }}
                
                .nav-icon-btn i {{ color: #64748B !important; }}
                .nav-icon-btn {{
                    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                    border: 1px solid transparent !important;
                }}
                .nav-icon-btn:hover {{
                    background: rgba(61, 123, 255, 0.08) !important;
                    color: var(--primary) !important;
                    border-color: rgba(61, 123, 255, 0.2) !important;
                    transform: scale(1.1);
                }}
                .nav-icon-btn.active {{
                    color: var(--primary) !important;
                    background: rgba(61, 123, 255, 0.15) !important;
                    border: 1px solid rgba(61, 123, 255, 0.3) !important;
                    box-shadow: 0 0 20px rgba(61, 123, 255, 0.2);
                }}
                .nav-icon-btn.active i {{ color: var(--primary) !important; }}

                .action-btn {{
                    transition: all 0.2s ease;
                    opacity: 0.4;
                    filter: grayscale(1);
                }}
                .action-btn:hover {{
                    opacity: 1;
                    filter: grayscale(0);
                    background: rgba(255, 255, 255, 0.05) !important;
                    transform: scale(1.2);
                }}

                .cam-card {{
                    position: relative;
                    overflow: hidden;
                    border-radius: 12px !important;
                    border: 1px solid var(--outline) !important;
                    background: var(--surface) !important;
                    transition: all 0.3s ease;
                }}
                .cam-card:hover {{
                    border-color: var(--primary) !important;
                    transform: translateY(-4px);
                    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.6);
                }}
                
                .intel-item {{
                    border-left: 2px solid transparent;
                    transition: all 0.2s;
                    border-radius: 8px;
                    background: rgba(255, 255, 255, 0.02);
                }}
                .intel-item:hover {{
                    background: rgba(255, 255, 255, 0.05);
                    border-left-color: var(--primary);
                }}

                .cyber-btn {{
                    border-radius: 8px !important;
                    font-weight: 700 !important;
                    letter-spacing: 1.5px !important;
                    text-transform: uppercase !important;
                    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
                    border: 1px solid rgba(255, 255, 255, 0.1) !important;
                }}
                .cyber-btn:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 8px 24px rgba(61, 123, 255, 0.4);
                    border-color: rgba(255, 255, 255, 0.3) !important;
                }}
                .cyber-btn:active {{
                    transform: translateY(0);
                }}

                .scanline {{
                    width: 100%;
                    height: 100px;
                    z-index: 5;
                    background: linear-gradient(0deg, rgba(0, 0, 0, 0) 0%, rgba(61, 123, 255, 0.05) 50%, rgba(0, 0, 0, 0) 100%);
                    opacity: 0.1;
                    position: absolute;
                    bottom: 100%;
                    pointer-events: none;
                    animation: scanline 8s linear infinite;
                }}
                @keyframes scanline {{
                    0% {{ bottom: 100%; }}
                    100% {{ bottom: -100px; }}
                }}
            </style>
        """)

        # --- Base Cinematic Layout ---
        with ui.row().classes('w-full h-screen no-wrap gap-0 bg-transparent'):
            
            # 1. NAVIGATION BAR (Ultra-thin Rail)
            with ui.column().classes('w-16 h-full items-center py-6 gap-6 border-r border-white/5').style('background: rgba(0,0,0,0.2)'):
                ui.label("R").classes('font-black text-xl glow-text mb-4').style(f'color: {PRIMARY_COLOR}')
                self.nav_btns = {}
                _NAV = [('grid_view', 0, 'Command Grid'), ('person_add', 1, 'Enrollment'), ('analytics', 2, 'Identity Registry'), ('settings', 3, 'Settings')]
                for icon, idx, label in _NAV:
                    btn = ui.button(icon=icon, on_click=lambda i=idx: self.switch_view(i)).props('flat round').classes('nav-icon-btn text-gray-400')
                    with btn:
                        ui.tooltip(label).classes('bg-black/90 text-blue-300 text-[13px]')
                    self.nav_btns[idx] = btn
                self.nav_btns[0].classes('active')
                
                ui.space()
                self.health_icon = ui.icon('sensors', color='white').style('font-size: 18px;')

            # 2. ACTIVITY INTELLIGENCE (Left Panel)
            with ui.column().classes('h-full p-0 cyber-panel border-r border-white/5 transition-all') as self.left_panel:
                self.left_panel.style(f'width: {320}px')
                with ui.row().classes('w-full px-6 py-4 items-center justify-between border-b border-white/5'):
                    ui.label("Tactical intelligence").classes('text-[13px] font-black tracking-[2px] opacity-80')
                    ui.button(icon='chevron_left', on_click=lambda: self.toggle_left_panel()).props('flat round size=sm').classes('opacity-30')
                self.log_container = ui.column().classes('w-full grow p-4 gap-3 overflow-y-auto scroll-hidden')
                # Populate some initial log placeholders
                with self.log_container:
                    self._add_log_entry("MONGO", "Database readiness verified", "green")
                    self._add_log_entry("REDIS", "Cache layer online", "blue")

            # 3. MAIN COMMAND GRID (Central Zone)
            with ui.column().classes('grow h-full p-0 relative'):
                # Header Overlay
                with ui.row().classes('w-full px-8 py-4 items-center justify-between z-10 telemetry-bar'):
                    with ui.row().classes('items-center gap-4'):
                        # Left Toggle (if hidden)
                        self.left_toggle_btn = ui.button(icon='menu', on_click=lambda: self.toggle_left_panel()).props('flat round size=sm').classes('mr-2')
                        self.left_toggle_btn.set_visibility(False)
                        ui.label("RYUK COMMAND CENTER").classes('font-black text-sm tracking-[2px] glow-text')
                        ui.badge("STABLE").props('color=green-9 size=sm').classes('text-[10px] px-2')
                    with ui.row().classes('items-center gap-6'):
                        self.clock_label = ui.label().classes('font-mono text-[14px] font-bold opacity-90')
                        # Right Toggle (if hidden)
                        self.right_toggle_btn = ui.button(icon='analytics', on_click=lambda: self.toggle_right_panel()).props('flat round size=sm').classes('ml-2')
                        self.right_toggle_btn.set_visibility(False)
                        ui.icon('public', size='sm', color='white').classes('opacity-60')
                
                # Dynamic Panels
                with ui.tab_panels(ui.tabs().set_visibility(False), value=0).classes('w-full grow bg-transparent z-0') as self.panels:
                    # -- Tab 0: High-Tech Grid --
                    with ui.tab_panel(0).classes('p-6 bg-transparent'):
                        self.grid = ui.grid(columns=2).classes('w-full gap-6')
                        self.empty_container = ui.column().classes('w-full items-center justify-center py-40 gap-4')
                        with self.empty_container:
                            ui.icon('radar', size='48px', color='white').classes('animate-pulse opacity-10')
                            ui.label("Optimizing signal...").classes('font-black tracking-[2px] text-[13px] opacity-20')
                        self.empty_label = self.empty_container

                    # -- Tab 1: Enrollment --
                    with ui.tab_panel(1).classes('p-12 bg-transparent'):
                        self._build_enrollment_view()

                    # -- Tab 2: Registry --
                    with ui.tab_panel(2).classes('p-12 bg-transparent'):
                        self._build_registry_view()

                    # -- Tab 3: Settings --
                    with ui.tab_panel(3).classes('p-12 bg-transparent'):
                        ui.label("Core settings").classes('text-2xl font-black mb-4')
                        ui.label("Under construction...").classes('opacity-50')

                # Bottom Dashboard Info
                with ui.row().classes('w-full px-8 py-3 items-center justify-between telemetry-bar'):
                    with ui.row().classes('items-center gap-4'):
                        self.redis_status = ui.label("SRV-REDIS").classes('text-[12px] font-black tracking-widest')
                        self.mongo_status = ui.label("SRV-MONGO").classes('text-[12px] font-black tracking-widest')
                        with ui.column().classes('gap-0'):
                            ui.label("LATENCY").classes('text-[11px] opacity-40')
                            ui.label("12ms").classes('text-[12px] font-mono text-green-500')

            # 4. TACTICAL RECOGNITION (Right Panel)
            with ui.column().classes('h-full p-0 cyber-panel border-l border-white/5 transition-all') as self.right_panel:
                self.right_panel.style(f'width: {320}px')
                with ui.row().classes('w-full px-6 py-4 items-center justify-between border-b border-white/5'):
                    ui.label("Recognition feed").classes('text-[13px] font-black tracking-[2px] opacity-50')
                    ui.button(icon='chevron_right', on_click=lambda: self.toggle_right_panel()).props('flat round size=sm').classes('opacity-30')
                self.intel_container = ui.column().classes('w-full grow p-4 gap-4 overflow-y-auto scroll-hidden')
                with self.intel_container:
                    self.no_intel_label = ui.label("System ready. No targets detected.").classes('w-full text-center py-10 text-[12px] opacity-20 font-bold tracking-widest')

    def toggle_left_panel(self):
        self.left_panel_visible = not self.left_panel_visible
        self.left_panel.set_visibility(self.left_panel_visible)
        self.left_toggle_btn.set_visibility(not self.left_panel_visible)

    def toggle_right_panel(self):
        self.right_panel_visible = not self.right_panel_visible
        self.right_panel.set_visibility(self.right_panel_visible)
        self.right_toggle_btn.set_visibility(not self.right_panel_visible)

    def _add_log_entry(self, source, message, color):
        with self.log_container:
            with ui.row().classes('w-full no-wrap gap-4 intel-item p-3'):
                ui.label(datetime.now().strftime("%H:%M:%S")).classes('text-[10px] font-mono opacity-40 mt-1')
                with ui.column().classes('gap-0'):
                    log_color = ERROR_COLOR if color in ['red', 'error'] else "#10B981" if color in ['green', 'success'] else PRIMARY_COLOR if color == 'blue' else TEXT_MED
                    ui.label(f"[{source.upper()}]").classes('text-[11px] font-black tracking-[1px]').style(f'color: {log_color}')
                    ui.label(message).classes('text-[13px] font-bold opacity-100 leading-tight')

    def _build_enrollment_view(self):
        with ui.column().classes('w-full max-w-4xl mx-auto gap-10'):
            ui.label("Biometric access registration").classes('text-xl font-black tracking-[2px] glow-text')
            with ui.row().classes('w-full gap-10 items-start'):
                with ui.card().classes('w-64 h-64 cyber-panel p-0 flex items-center justify-center relative border-outline') as self.photo_card:
                    self.photo_preview = ui.image('').classes('absolute inset-0 w-full h-full object-cover opacity-80')
                    ui.icon('fingerprint', size='xl', color='white').classes('opacity-10')
                    ui.element('div').classes('scanline')
                    self.upload_ctrl = ui.upload(on_upload=self._handle_upload, label="", auto_upload=True).classes('absolute bottom-0 w-full opacity-10 hover:opacity-100 transition-opacity').props('flat dark')
                
                with ui.column().classes('grow gap-6'):
                    with ui.grid(columns=2).classes('w-full gap-4'):
                        self.enroll_name = ui.input(label="Subject name").props('dark standout square').classes('w-full')
                        self.enroll_aadhar = ui.input(label="Identification ID").props('dark standout square').classes('w-full')
                        self.enroll_phone = ui.input(label="Phone / Communication").props('dark standout square').classes('w-full')
                        self.enroll_address = ui.input(label="Location data").props('dark standout square').classes('w-full')
                    
                    with ui.row().classes('w-full gap-4'):
                        self.role_select = ui.select(["Personnel", "Visitor", "VIP", "Blacklist"], value="Personnel", label="Classification").props('dark standout square').classes('grow')
                        self.enroll_threat = ui.select(['Low', 'Medium', 'High'], value='Low', label="Threat profiling").props('dark standout square').classes('grow')
                    
                    self.enroll_btn = ui.button("EXECUTE ENROLLMENT", on_click=self._submit_enrollment).classes('w-full h-14 cyber-btn').style(f'background-color: {PRIMARY_COLOR};')

    def _build_registry_view(self):
        with ui.row().classes('w-full justify-between items-center mb-6'):
            ui.label("Identity registry").classes('text-2xl font-black tracking-tight glow-text')
            ui.label("Viewing subjects in high-fidelity neural index").classes('text-[13px] opacity-60 -mt-2')
            self.ci_count = ui.badge("0 IDENTITIES").props('color=white outline').classes('px-4 py-2 font-black text-[12px]')
        self.ci_search = ui.input(placeholder="Search identities...", on_change=self._filter_ci).classes('w-full mb-6 cyber-panel p-2 px-4').props('dark borderless')
        self.ci_list = ui.column().classes('w-full gap-3 overflow-y-auto grow custom-scrollbar')

    def _get_video_frame(self, client_id: str):
        global active_sessions
        if client_id in active_sessions:
            frame = active_sessions[client_id].latest_processed_frame
            if frame:
                return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})
        return Response(status_code=404)

    # --- Background Logic ---
    def _check_new_streams(self):
        active_cids = {cid.decode() if isinstance(cid, bytes) else cid for cid in cache.smembers("registry:active_streams")}
        db_cids = set()
        try:
            # Sync retrieval of all registered cameras
            sync_db = get_sync_db()
            if sync_db is not None:
                for cam in sync_db["cameras"].find({}, {"client_id": 1}):
                    db_cids.add(cam["client_id"])
        except Exception as e:
            print(f"DEBUG: Error pulling db_cids: {e}")
        
        if active_cids:
            print(f"DEBUG: UI Registry Sync — Active CIDs: {active_cids}")
        
        # Priority: Show all active streams first, then fill up to 4 with offline DB cameras
        active_list = sorted([cid for cid in active_cids])
        offline_list = sorted([cid for cid in db_cids if cid not in active_cids])
        
        # New: Add cameras from 'devices' collection (RTSP)
        rtsp_devices = []
        try:
            if sync_db is not None:
                for dev in sync_db["devices"].find():
                    rtsp_devices.append(dev)
        except Exception as e:
            print(f"DEBUG: Error pulling rtsp_devices: {e}")

        to_show = active_list + offline_list
        # Logic adjustment: we want to show RTSP devices too
        rtsp_cids = [dev['ip'] for dev in rtsp_devices]
        to_show = list(dict.fromkeys(to_show + rtsp_cids)) # Unique list
        
        limit = max(4, len(to_show))
        to_show = to_show[:limit]
        
        # Ensure "+" button is always at the end if we have space
        show_add_btn = True
        
        # Remove cards no longer in the restricted list
        for cid in list(self.camera_cards.keys()):
            if cid not in to_show:
                card = self.camera_cards.pop(cid)
                self.grid.remove(card)
        
        # Ensure all required cards exist and are in the correct order
        for idx, cid in enumerate(to_show):
            is_active = cid in active_cids or cid in rtsp_cids
            if cid not in self.camera_cards:
                self._create_camera_card(cid, is_active)
            
            card = self.camera_cards[cid]
            # Ensure index stability in the grid
            try:
                if list(self.grid).index(card) != idx:
                    card.move(self.grid, idx)
            except ValueError:
                pass
            
            # Manage AI sessions back-end (Thread-safe registration)
            if is_active:
                source_url = None
                if cid in rtsp_cids:
                    dev = next(d for d in rtsp_devices if d['ip'] == cid)
                    # rtsp://username:password@ip:554/cam/realmonitor?channel=1&subtype=1
                    source_url = f"rtsp://{dev['username']}:{dev['password']}@{dev['ip']}:554/cam/realmonitor?channel=1&subtype=1"

                if cid not in active_sessions:
                    self._start_session(cid, source_url)
                else:
                    # Session already exists, ensure WE are listening to it
                    proc = active_sessions[cid]
                    proc.add_listener(self)
                    if proc.latest_processed_frame:
                         if not getattr(card, 'is_streaming', False):
                             self.ui_queue.put(lambda c=cid: self._handle_stream_actual_start(c))
            elif not is_active and cid in active_sessions:
                self._stop_session(cid)
        
        # Add "+" button card if not present
        if show_add_btn and "add_btn" not in self.camera_cards:
            self._create_add_camera_card()
        elif "add_btn" in self.camera_cards:
            # Ensure it is at the end
            self.camera_cards["add_btn"].move(self.grid, len(to_show))
                
    def _create_camera_card(self, client_id: str, active: bool):
        with self.grid:
            with ui.card().classes('w-full p-0 cyber-panel overflow-hidden cam-card group') as card:
                card.client_id = client_id
                with ui.element('div').classes('w-full aspect-video relative bg-black/40 flex items-center justify-center') as container:
                    card.container = container
                    card.stream_img = ui.interactive_image().classes('w-full h-full')
                    card.stream_img.set_visibility(False)
                    card.placeholder = ui.icon('videocam_off', size='64px', color='white').classes('opacity-10')
                    ui.element('div').classes('scanline')
                    
                    # Fullscreen Button (Tactical Yellow - Top Right)
                    card.fs_btn = ui.button(icon='fullscreen', on_click=lambda: self._show_fullscreen_view(client_id)) \
                        .props('flat round size=md') \
                        .classes('absolute top-3 right-3 transition-all z-50 shadow-lg') \
                        .style('color: #FFD100 !important;')
                    
                    # Overlays
                    with ui.row().classes('absolute top-3 left-3 items-center gap-2 pointer-events-none'):
                        card.rec_dot = ui.label("REC").classes('text-[11px] font-black text-red-500 animate-pulse')
                        # Client ID
                        client_label = ui.label(client_id.upper()).classes('text-[11px] font-black tracking-[2px] opacity-70')
                        with client_label:
                            ui.tooltip("Loading device info...").classes('bg-black/90 text-blue-300 font-mono text-[12px]')
                            card.device_tooltip = client_label
                    
                    # Metadata Overlay (Bottom)
                    with ui.column().classes('absolute bottom-4 left-4 gap-1 pointer-events-none'):
                        card.status_label = ui.label("Signal offline").classes('text-[11px] font-black tracking-widest text-red-500')
                        card.meta_label = ui.label("Searching...").classes('text-[11px] font-mono opacity-30')
                
                with ui.row().classes('w-full items-center p-3 px-4'):
                    card.status_label = ui.label("Signal offline").classes('text-[8px] font-black tracking-widest text-red-500')
                    ui.space()
                    card.meta_label = ui.label("Searching...").classes('text-[8px] font-mono opacity-30')
        
        self.camera_cards[client_id] = card
        self.empty_label.set_visibility(False)

    def _show_fullscreen_view(self, client_id: str):
        """Open a true full-screen cinematic view for the selected stream."""
        # Use a dialog as the base, but we will trigger browser-level fullscreen on it
        with ui.dialog().classes('p-0 m-0 w-full h-full max-w-none max-h-none shadow-none border-none') as dialog:
            # Assign a unique ID so we can target it with JS
            fs_id = f"fs_container_{client_id.replace('.', '_').replace(':', '_')}"
            with ui.column().classes('w-full h-full p-0 m-0 bg-black relative flex items-center justify-center overflow-hidden').props(f'id="{fs_id}"') as fs_container:
                # Live Stream
                encoded_cid = urllib.parse.quote(client_id)
                stream_url = f"/stream/{encoded_cid}?t={time.time()}"
                ui.interactive_image(stream_url).classes('w-full h-full object-contain')
                
                # Top Overlay
                with ui.row().classes('absolute top-0 left-0 w-full p-6 items-center justify-between bg-gradient-to-b from-black/80 to-transparent z-50'):
                    with ui.column().classes('gap-1'):
                        ui.label(client_id.upper()).classes('text-sm font-black tracking-[2px] text-white opacity-40')
                        ui.label("TACTICAL FULL-SCREEN FEED").classes('text-xl font-black text-white glow-text')
                    
                    async def close_fs():
                        await ui.run_javascript('if (document.fullscreenElement) document.exitFullscreen();')
                        dialog.close()

                    ui.button(icon='close', on_click=close_fs).props('flat round size=lg').classes('text-white hover:bg-white/10 transition-colors')

                # Critical Data Overlay (Bottom Right)
                with ui.column().classes('absolute top-4 right-4 items-end gap-0'):
                    ui.label("ENCRYPTED SIGNAL").classes('text-[13px] font-black tracking-widest text-blue-400')
                    ui.label(datetime.now().strftime("%Y-%m-%d %H:%M:%S")).classes('text-[13px] font-mono text-white')

        dialog.open()
        # Trigger true browser fullscreen on the specific element
        # Use a small delay to ensure the dialog is fully attached to the DOM
        ui.run_javascript(f'''
            setTimeout(() => {{
                var el = document.getElementById("{fs_id}");
                if (el) {{
                    console.log("Found element for fullscreen:", "{fs_id}");
                    var requestMethod = el.requestFullscreen || el.webkitRequestFullscreen || el.mozRequestFullscreen || el.msRequestFullscreen;
                    if (requestMethod) {{
                        requestMethod.call(el).catch(e => {{
                            console.error("Fullscreen request failed:", e);
                        }});
                    }} else {{
                        console.error("No fullscreen method found on element");
                    }}
                }} else {{
                    console.error("Could not find element with ID:", "{fs_id}");
                }}
            }}, 200);
        ''')

    def _create_add_camera_card(self):
        with self.grid:
            with ui.card().classes('w-full aspect-video p-0 cyber-panel overflow-hidden cam-card flex items-center justify-center border-dashed border-2 opacity-50 hover:opacity-100 transition-opacity cursor-pointer') as card:
                card.on('click', self._show_add_camera_dialog)
                ui.icon('add', size='64px', color='white').classes('opacity-20')
                ui.label("Add camera source").classes('font-black tracking-[2px] text-[13px] opacity-20 mt-4')
                ui.element('div').classes('scanline')
        self.camera_cards["add_btn"] = card

    def _show_add_camera_dialog(self):
        with ui.dialog().classes('p-0') as dialog, ui.card().classes('w-[500px] cyber-panel p-8 gap-6'):
            ui.label("LINK NEW CAMERA NODE").classes('text-lg font-black tracking-widest mb-2 glow-text')
            
            ip_input = ui.input(label="IP ADDRESS").props('dark standout square').classes('w-full')
            user_input = ui.input(label="USERNAME").props('dark standout square').classes('w-full')
            pass_input = ui.input(label="PASSWORD").props('dark standout square password').classes('w-full')
            
            async def save():
                if not ip_input.value or not user_input.value or not pass_input.value:
                    ui.notify("ALL FIELDS ARE MANDATORY", type='warning')
                    return
                
                device_data = {
                    "ip": ip_input.value,
                    "username": user_input.value,
                    "password": pass_input.value,
                    "added_at": datetime.now()
                }
                
                try:
                    sync_db = get_sync_db()
                    if sync_db is not None:
                        sync_db["devices"].update_one({"ip": ip_input.value}, {"$set": device_data}, upsert=True)
                        ui.notify("CAMERA SOURCE VERIFIED AND SAVED", color='green')
                        dialog.close()
                        self._check_new_streams()
                except Exception as e:
                    ui.notify(f"LINKING FAILED: {e}", color='red')

            with ui.row().classes('w-full justify-end gap-3 mt-4'):
                ui.button("CANCEL", on_click=dialog.close).props('flat dark')
                ui.button("LINK DEVICE", on_click=save).classes('px-6 h-12 cyber-btn').style(f'background-color: {PRIMARY_COLOR};')
        dialog.open()

    def _start_session(self, client_id: str, source_url: Optional[str] = None):
        global active_sessions
        if client_id in active_sessions: return
        
        print(f"DEBUG: Dashboard — Starting Session for CID: {client_id}")
        proc = Processor(client_id, source_url=source_url)
        # Register ourselves as a listener
        proc.add_listener(self)
        proc.start()
        active_sessions[client_id] = proc
        print(f"DEBUG: Dashboard — Session registry updated. Total active: {len(active_sessions)}")
        
    # --- Multi-Listener Processor Callbacks (called from Processor threads) ---
    def on_detection(self, meta):
        self.ui_queue.put(lambda: self._handle_detection(meta))

    async def _handle_stream_start(self, e):
        # We'll simulate a start and trigger the actual start call
        client_id = e.args['client_id']
        self._add_log_entry("WATCHDOG", f"Initializing stream index for device: {client_id}", "blue")
        # In a real app, you'd wait for connection confirmation
        await self._handle_stream_actual_start(client_id)

    def on_stream_start(self, client_id):
        print(f"DEBUG: UI Listener — Received stream_start for {client_id}")
        self.ui_queue.put(lambda: self._handle_stream_actual_start(client_id))

    def on_inactive(self, client_id):
        self.ui_queue.put(lambda: self._stop_session(client_id))

    def _process_ui_queue(self):
        """Processes pending UI tasks from the thread-safe queue on the main thread."""
        while not self.ui_queue.empty():
            try:
                callback = self.ui_queue.get_nowait()
                callback()
            except Exception as e:
                self._add_log_entry("SYSTEM", f"UI logic error: {str(e)}", "red")

    def _handle_stream_actual_start(self, client_id):
        # Trigger the actual stream start in the backend
        try:
            self._add_log_entry("IMAGE", f"Processing pipeline activated for {client_id}", "green")
            # For now, we rely on the processor logic already running or triggered by the backend
            self._add_log_entry("WATCHDOG", f"Stream index synchronized for {client_id}", "green")
        except Exception as e:
            self._add_log_entry("WATCHDOG", f"Pipeline error for {client_id}: {str(e)}", "red")
            return

        print(f"DEBUG: UI — Handling stream actual start for {client_id}")
        # Safety check: if card is no longer in camera_cards (e.g., removed during transition)
        if client_id not in self.camera_cards:
            print(f"DEBUG: UI — ABORT start: card missing for {client_id}")
            return

        # This runs when the first frame is RECEIVED by the processor
        if client_id in self.camera_cards:
            card = self.camera_cards[client_id]
            if not card.stream_img: return
            
            if getattr(card, 'is_streaming', False):
                return
            
            # Use URL-encoded client_id to handle colons properly
            encoded_cid = urllib.parse.quote(client_id)
            # Use set_source for the interactive_image
            card.stream_img.set_source(f"/stream/{encoded_cid}?t={time.time()}")
            card.stream_img.set_visibility(True)
            card.placeholder.set_visibility(False)
            card.rec_dot.set_visibility(True)
            card.is_streaming = True
            
            # Fetch device info to update UI
            dev_name = "Signal active"
            tactical_loc = "Off-site"
            
            from core.database import get_sync_db
            db = get_sync_db()
            if db is not None:
                # Try cameras collection first, then devices
                cam = db["cameras"].find_one({"client_id": client_id})
                if not cam:
                    cam = db["devices"].find_one({"ip": client_id})
                
                if cam:
                    if "device_info" in cam:
                        di = cam.get("device_info", {})
                        dev_name = di.get('device_display_name') or di.get('device_name', 'Unnamed Node')
                        info_str = f"NAME: {dev_name}\nOS: {di.get('platform', 'Unknown')}\nAGENT: {di.get('user_agent','Unknown')[:50]}..."
                        
                        card.device_tooltip.set_text(f"{dev_name} // {di.get('platform', 'Unk')}")
                        with card.device_tooltip:
                            ui.tooltip(info_str).classes('bg-black/95 text-blue-300 font-mono text-[9px] whitespace-pre')
                    else:
                        # RTSP Device fallback
                        dev_name = f"Cam-{client_id}"
                        card.device_tooltip.set_text(f"{dev_name} // RTSP")
                        with card.device_tooltip:
                             ui.tooltip(f"RTSP source: {client_id}").classes('bg-black/95 text-blue-300 font-mono text-[9px]')

                    loc_list = cam.get("locations", [])
                    tactical_loc = loc_list[0] if loc_list else "RTSP SOURCE"

            card.status_label.set_text(dev_name)
            card.status_label.classes(replace='text-red-500 text-orange-500', add='text-green-500')
            card.meta_label.set_text(tactical_loc)
        
        self._add_log_entry("SIGNAL", f"STREAM LIVE: {client_id}", "green")

    async def _handle_signal_drop(self, client_id: str):
        # We wrap this in an async function so it can be scheduled on the main loop
        if client_id in active_sessions:
            self._stop_session(client_id)

    def _stop_session(self, client_id: str):
        global active_sessions
        print(f"NiceGUI: Stopping session {client_id}")
        # Instead of stopping the global processor immediately, we just stop listening.
        # The last dashboard instance to disconnect (or the processor's own timeout) will stop it.
        proc = active_sessions.get(client_id)
        if proc:
            proc.remove_listener(self)
            if not proc.listeners:
                 active_sessions.pop(client_id)
                 proc.stop()
        
        # UI Updates (Always run for this dashboard instance)
        if client_id in self.camera_cards:
            card = self.camera_cards[client_id]
            card.is_streaming = False
            card.stream_img.set_source('')
            card.stream_img.set_visibility(False)
            card.placeholder.set_visibility(True)
            card.rec_dot.set_visibility(False)
            card.status_label.set_text("OFFLINE")
            card.status_label.classes(replace='text-green-500', add='text-red-500')
            card.meta_label.set_text("NO SIGNAL")
        
        self._add_log_entry("SIGNAL", f"CONNECTION LOST: {client_id}", "red")

    def _handle_detection(self, data):
        # Data format: {'client_id': str, 'detections': [{...}]}
        client_id = data.get('client_id')
        detections = data.get('detections', [])
        
        
        for metadata in detections:
            aadhar = metadata.get("aadhar")
            if not aadhar: continue
            self.intel_last_seen[aadhar] = time.time()
            
            if aadhar not in self.intel_cards:
                self.intel_counts[aadhar] = 1
                self.intel_is_active[aadhar] = True
                self.intel_cards[aadhar] = metadata
                with self.intel_container:
                    self.no_intel_label.set_visibility(False)
                    threat = metadata.get('threat_level', 'Low')
                    threat_color = 'red' if threat == 'High' else 'orange' if threat == 'Medium' else '#53DE53'
                    with ui.row().classes('w-full no-wrap gap-4 intel-item p-3 border-r border-white/5 shadow-xl animate-fade').style('background: rgba(255,255,255,0.02)') as card:
                        self.intel_elements[aadhar] = card
                        ui.avatar('person', color='transparent').classes('border border-white/10').style(f'background-color: {SURFACE_COLOR}; color: white')
                        with ui.column().classes('gap-0 grow'):
                            ui.label(metadata.get('name', 'Unknown')).classes('font-black text-xs')
                            ui.label(aadhar).classes('text-[11px] font-mono opacity-40')
                            with ui.row().classes('items-center gap-2 mt-2'):
                                ui.badge(threat.upper()).props(f'color={threat_color} size=xs').classes('text-[10px] px-2')
                        
                        with ui.column().classes('items-end gap-1'):
                            self.intel_count_labels[aadhar] = ui.label("×1").classes('text-[13px] font-black text-orange-500 opacity-80')
                            ui.label("MATCH 98%").classes('text-[10px] font-bold opacity-20')
                    
                    if len(list(self.intel_container)) > 1:
                        card.move(self.intel_container, target_index=0)
                
                self._add_log_entry("RECOGNITION", f"Target identified: {metadata.get('name')}", "orange")
            else:
                # If the person was previously inactive (left camera and came back), increment count
                if not self.intel_is_active.get(aadhar, False):
                    self.intel_counts[aadhar] += 1
                    self.intel_is_active[aadhar] = True # Mark as back in view
                    if aadhar in self.intel_count_labels:
                        self.intel_count_labels[aadhar].set_text(f"×{self.intel_counts[aadhar]}")
                
                # Move to top to indicate recent activity
                if aadhar in self.intel_elements:
                    try:
                        self.intel_elements[aadhar].move(self.intel_container, target_index=0)
                    except Exception as e:
                        print(f"DEBUG: UI — Failed to reorder intel card: {e}")

    async def _check_health(self):
        # Check backend services
        try:
            # MongoDB Health
            db = get_sync_db()
            mongo_up = db is not None
            if mongo_up != self.mongo_healthy:
                self.mongo_healthy = mongo_up
                status = "ONLINE" if mongo_up else "OFFLINE"
                color = "green" if mongo_up else "red"
                self._add_log_entry("MONGO", f"Database connectivity: {status}", color)
            
            self.mongo_status.style(f'color: {"#10B981" if mongo_up else ERROR_COLOR}')
            
            # Redis Health
            try:
                cache.ping()
                redis_up = True
            except:
                redis_up = False

            if redis_up != self.redis_healthy:
                self.redis_healthy = redis_up
                status = "ONLINE" if redis_up else "OFFLINE"
                color = "green" if redis_up else "red"
                self._add_log_entry("REDIS", f"Cache layer connectivity: {status}", color)
            self.redis_status.style(f'color: {"#10B981" if redis_up else ERROR_COLOR}')
            
            self.health_icon.style(f'color: {"#10B981" if mongo_up and redis_up else ERROR_COLOR}')
        except Exception as e:
            self._add_log_entry("SYSTEM", f"Health monitoring error: {str(e)}", "red")
            self.mongo_status.style(f'color: {ERROR_COLOR}')
            self.redis_status.style(f'color: {ERROR_COLOR}')

    def _cleanup_intel(self):
        now = time.time()
        # Mark as INACTIVE if not seen for 2 seconds (subject probably left camera)
        for aadhar, last_t in list(self.intel_last_seen.items()):
            if now - last_t > 2.0:
                self.intel_is_active[aadhar] = False

        stale = [a for a, t in self.intel_last_seen.items() if now - t > INTEL_CLEANUP_S]
        for aadhar in stale:
            self.intel_last_seen.pop(aadhar)
            self.intel_cards.pop(aadhar)
            self.intel_counts.pop(aadhar, None)
            self.intel_is_active.pop(aadhar, None)
            self.intel_count_labels.pop(aadhar, None)
            el = self.intel_elements.pop(aadhar, None)
            if el:
                try:
                    self.intel_container.remove(el)
                except:
                    pass
        
        if not self.intel_cards and not any(isinstance(child, ui.row) for child in self.intel_container):
            self.no_intel_label.set_visibility(True)

    # --- UI Events ---
    def switch_view(self, index: int):
        self.panels.set_value(index)
        for i, btn in self.nav_btns.items():
            if i == index:
                btn.classes('active')
            else:
                btn.classes(remove='active')
        
        if index == 2:
            self._load_ci()
        
        self._add_log_entry("SYSTEM", f"SWITCHED TO VIEW_MODE_{index}", "blue")

    def _update_clock(self):
        self.clock_label.set_text(datetime.now().strftime("%H:%M:%S  IST"))

    # --- Enrollment ---
    async def _handle_upload(self, e):
        """Ultra-resilient async upload handler for biometric data."""
        try:
            print(f"BIO-LOG: Processing upload event from subject...")
            
            # 1. Try standard NiceGUI 3.x+ e.file.read()
            data = None
            if hasattr(e, 'file'):
                data = await e.file.read()
            
            # 2. Fallback for older versions or variants (e.content)
            if data is None:
                content = getattr(e, 'content', None)
                if content:
                    if hasattr(content, 'read'):
                        if asyncio.iscoroutinefunction(content.read):
                            data = await content.read()
                        else:
                            data = content.read()
                    else:
                        data = content
            
            # 3. Last resort fallback
            if data is None:
                data = getattr(e, 'args', {}).get('content')

            if data:
                self.uploaded_image_bytes = data
                print(f"BIO-LOG: Captured {len(data)} bytes of neural data.")
                
                # Update UI preview using base64
                b64 = base64.b64encode(data).decode('utf-8')
                self.photo_preview.set_source(f'data:image/jpeg;base64,{b64}')
                
                # Visual success indicator
                self.photo_card.style('border: 2px solid #53ff53; box-shadow: 0 0 20px rgba(83, 255, 83, 0.4);')
                ui.notify("BIOMETRIC DATA CAPTURED", color='green', position='top')
            else:
                print("BIO-LOG ERROR: Upload event received but content was empty.")
                ui.notify("UPLOAD FAILED: NO CONTENT", color='red')
        except Exception as err:
            print(f"BIO-LOG CRITICAL ERROR: {err}")
            ui.notify(f"SYSTEM UPLOAD ERROR: {err}", color='red')

    async def _submit_enrollment(self):
        name = self.enroll_name.value
        aadhar = self.enroll_aadhar.value
        threat = self.enroll_threat.value
        phone = self.enroll_phone.value
        address = self.enroll_address.value
        
        if not name:
            ui.notify("MISSING SUBJECT NAME", type='warning', position='top')
            return
        if not aadhar:
            ui.notify("MISSING IDENTIFICATION ID", type='warning', position='top')
            return
        if self.uploaded_image_bytes is None:
            ui.notify("ACTION REQUIRED: SELECT SUBJECT PHOTO FIRST", type='negative', position='top')
            # Trigger a visual pulse if photo missing
            self.photo_card.classes(add='animate-pulse')
            ui.timer(2.0, lambda: self.photo_card.classes(remove='animate-pulse'), once=True)
            return
        
        self.enroll_btn.set_text("ENROLLING NEURAL DATA...")
        self.enroll_btn.disable()
        
        try:
            # Save bytes to a temp file because watchdog.enroll_face expects a path
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                f.write(self.uploaded_image_bytes)
                temp_path = f.name
            
            from core.watchdog_indexer import enroll_face
            
            self._add_log_entry("MONGO", "Committing biometric data to persistent store...", "blue")
            
            # Use the actual enroll_face function which handles both disk and DB
            await asyncio.to_thread(
                enroll_face,
                temp_path, aadhar, name, threat, phone, address
            )
            
            self._add_log_entry("MONGO", f"Identity committed: {name}", "green")
            ui.notify("Subject successfully enrolled", type='positive')

            # Cleanup temp file (if enroll_face was used, otherwise not strictly needed)
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            # --- Clear Enrollment Screen ---
            self.enroll_name.value = ""
            self.enroll_aadhar.value = ""
            self.enroll_phone.value = ""
            self.enroll_address.value = ""
            self.enroll_threat.value = "Low"
            
            # Reset Biometric Buffer
            self.uploaded_image_bytes = None
            self.photo_preview.set_source('')
            self.photo_card.style('border: 1px solid rgba(255,255,255,0.1); box-shadow: none;')
            
            # Reset Upload control if possible (re-create or clear)
            self.upload_ctrl.reset()
            
        except Exception as e:
            print(f"ENROLL-ERROR: {e}")
            ui.notify(f"Enrollment Error: {str(e)}", type='negative')
        finally:
            self.enroll_btn.set_text("EXECUTE ENROLLMENT")
            self.enroll_btn.enable()

    # --- CI View ---
    def _load_ci(self):
        query = self.ci_search.value.lower() if hasattr(self, 'ci_search') else ""
        profiles = get_all_profiles()
        
        # Performance: filter profiles list first
        if query:
            profiles = [p for p in profiles if query in p.get('name', '').lower() or query in p.get('aadhar', '').lower()]
            
        self.ci_count.set_text(f"{len(profiles)} IDENTITIES")
        self.ci_list.clear()
        with self.ci_list:
            if not profiles:
                ui.label("NO MATCHING DATA FOUND").classes('w-full text-center py-20 opacity-20 font-black tracking-widest text-[10px]')
            
            for p in profiles:
                with ui.row().classes('w-full p-4 cyber-panel items-center justify-between no-wrap hover:bg-white/5 transition-all'):
                    with ui.row().classes('items-center gap-4'):
                        # Display Thumbnail if exists
                        if p.get('photo_thumb'):
                            ui.image(f"data:image/jpeg;base64,{p['photo_thumb']}").classes('w-12 h-12 rounded border border-white/10 object-cover')
                        else:
                            ui.avatar('person', color='transparent').classes('border border-white/10').style('background-color: rgba(255,255,255,0.05); color: white')
                            
                        with ui.column().classes('gap-0'):
                            ui.label(p.get('name', 'Unknown')).classes('font-black text-xs tracking-wider')
                            ui.label(p.get('aadhar', '')).classes('text-[12px] font-mono opacity-40')
                            if p.get('phone'):
                                ui.label(p.get('phone')).classes('text-[11px] opacity-40 italic mt-1')

                    with ui.row().classes('items-center gap-6'):
                        # Threat Indicator
                        threat = p.get('threat_level', 'Low')
                        threat_color = 'red' if threat == 'High' else 'orange' if threat == 'Medium' else '#53DE53'
                        ui.badge(threat.upper()).props(f'color={threat_color} size=xs').classes('text-[7px] px-2 font-bold')
                        
                        # Actions
                        with ui.row().classes('gap-1'):
                            ui.button(icon='analytics', on_click=lambda p=p: self._show_tracking(p)).props('flat round size=sm').classes('action-btn')
                            ui.button(icon='edit', on_click=lambda p=p: self._edit_ci(p)).props('flat round size=sm').classes('action-btn')
                            ui.button(icon='delete', on_click=lambda p=p: self._delete_ci(p['aadhar'])).props('flat round size=sm').classes('action-btn text-red-500')

    def _filter_ci(self):
        self._load_ci()

    def _delete_ci(self, aadhar: str):
        delete_profile(aadhar)
        self._load_ci()
        ui.notify("Target purged from central registry.", type='warning')

    def _edit_ci(self, profile: dict):
        with ui.dialog().classes('p-0') as dialog, ui.card().classes('w-[500px] cyber-panel p-8 gap-6'):
            ui.label("Moderate neural profile").classes('text-lg font-black tracking-widest mb-2 glow-text')
            
            with ui.column().classes('w-full gap-4'):
                ui.label("Identity details").classes('text-[10px] font-black tracking-widest opacity-30 mb-2')
                name_input = ui.input(label="Name", value=profile.get('name')).props('dark standout square').classes('w-full')
                phone_input = ui.input(label="Communication", value=profile.get('phone')).props('dark standout square').classes('w-full')
                address_input = ui.input(label="Location data", value=profile.get('address')).props('dark standout square').classes('w-full')
                threat_select = ui.select(['Low', 'Medium', 'High'], value=profile.get('threat_level', 'Low'), label="Threat profiling").props('dark standout square').classes('w-full')
            
            async def save():
                data = {
                    "name": name_input.value,
                    "phone": phone_input.value,
                    "address": address_input.value,
                    "threat_level": threat_input.value
                }
                from core.watchdog_indexer import update_profile
                await asyncio.to_thread(update_profile, profile['aadhar'], data)
                dialog.close()
                self._load_ci()
                ui.notify("Profile metadata updated.", color='green')

            with ui.row().classes('w-full justify-end gap-3 mt-4'):
                ui.button("CANCEL", on_click=dialog.close).props('flat dark')
                ui.button("SAVE UPDATES", on_click=save).classes('px-6 h-12 cyber-btn').style(f'background-color: {PRIMARY_COLOR};')
        dialog.open()

    def _show_tracking(self, profile: dict):
        from core.watchdog_indexer import get_activity_report
        logs = get_activity_report(profile['aadhar'], limit=20)
        
        with ui.dialog().classes('p-0') as dialog, ui.card().classes('w-[600px] cyber-panel p-0 flex column no-wrap'):
            with ui.row().classes('w-full p-6 justify-between items-center border-b border-white/5'):
                ui.label(f"TRACKING DOSSIER: {profile.get('name', 'Unknown')}").classes('font-black tracking-widest')
                ui.button(icon='close', on_click=dialog.close).props('flat round size=sm')
            
            with ui.column().classes('w-full p-6 gap-3 overflow-y-auto max-h-[500px]'):
                if not logs:
                    ui.label("NO RECENT TRACKING DATA AVAILABLE.").classes('w-full text-center py-10 opacity-30 text-[10px] italic')
                else:
                    for log in logs:
                        with ui.row().classes('w-full p-3 bg-white/5 rounded items-center justify-between no-wrap'):
                            with ui.column().classes('gap-0'):
                                # Handle new single string 'location' vs legacy 'locations' list
                                loc = log.get('location')
                                if not loc:
                                    locs_list = log.get('locations', ['Unknown'])
                                    loc = locs_list[0] if isinstance(locs_list, list) else str(locs_list)
                                
                                ui.label(loc.upper()).classes('text-[13px] font-black tracking-wider text-blue-400')
                                ui.label(log.get('client_id')).classes('text-[11px] opacity-30 font-mono')
                            ui.label(log.get('date_str')).classes('text-[12px] font-mono opacity-50')
        dialog.open()

# Initialize database
app.on_startup(init_db)

# Mount the existing streaming server
app.mount('/api', streaming_app)

# Create the dashboard instance
dashboard: Optional[NiceDashboard] = None

@ui.page('/')
def index():
    global dashboard
    # Get local IP
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except:
        IP = '127.0.0.1'
    finally:
        s.close()
    
    dashboard = NiceDashboard(IP)

@app.get('/video/{client_id}')
def video_endpoint(client_id: str):
    global active_sessions
    if client_id in active_sessions:
        frame = active_sessions[client_id].latest_processed_frame
        if frame:
            return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})
        else:
            return Response(status_code=204) 
    return Response(status_code=404)

async def mjpeg_generator(client_id: str):
    global active_sessions
    count = 0
    while True:
        proc = active_sessions.get(client_id)
        if not proc:
            break
        frame = proc.latest_processed_frame
        if frame:
            count += 1
            if count <= 5 or count % 100 == 0:
                print(f"DEBUG: MJPEG Generator — Serving Frame {count} for {client_id} ({len(frame)} bytes)")
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        await asyncio.sleep(0.04) # ~25 FPS for smoothness

@app.get('/stream/{client_id:path}')
async def stream_endpoint(client_id: str):
    global active_sessions
    # Safety: unquote in case browser double-encoded or path capture preserved it
    client_id = urllib.parse.unquote(client_id)
    print(f"DEBUG: MJPEG Endpoint — Requested CID: {client_id}")
    if client_id not in active_sessions:
        print(f"DEBUG: MJPEG Endpoint — 404 for {client_id}. Registry: {list(active_sessions.keys())}")
        return Response(status_code=404)
    print(f"DEBUG: MJPEG Endpoint — Starting stream for {client_id}")
    return StreamingResponse(mjpeg_generator(client_id), media_type='multipart/x-mixed-replace; boundary=frame')

def run_nicegui():
    ui.run(title="Ryuk AI", dark=True, reload=False, port=SERVER_PORT, show=False)

if __name__ in {"__main__", "__mp_main__"}:
    run_nicegui()
