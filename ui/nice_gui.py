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

from core.state import cache, cache_str
from core.database import get_sync_db, profiles_col, cameras_col
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
BG_COLOR = "#1A001A" # Even darker base for contrast
SURFACE_GRADIENT = "linear-gradient(145deg, #380036 0%, #250024 100%)"
SURFACE_COLOR = "#380036"
PRIMARY_COLOR = "#DE6E4B" # Keeping terracotta for highlight unless asked otherwise
ACCENT_COLOR = "#315C2B"  
ERROR_COLOR = "#DE6E4B"   
TEXT_HIGH = "#FFFFFF"
TEXT_MED = "#F5D3F5"      # Light Magenta/Lavender
OUTLINE_COLOR = "#4D004A"
GLOW_COLOR = "0 0 15px rgba(222, 110, 75, 0.4)"

# Global state for background tasks and shared endpoints
active_sessions: Dict[str, Processor] = {}

class NiceDashboard:
    def __init__(self, ip_address: str):
        self.ip_address = ip_address
        self.intel_cards: Dict[str, dict] = {} # aadhar -> metadata
        self.intel_last_seen: Dict[str, float] = {} # aadhar -> time
        self.redis_healthy = False
        self.mongo_healthy = False
        
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
        ui.query('body').style(f'background-color: {BG_COLOR}; color: {TEXT_HIGH}; font-family: "Inter", "JetBrains Mono", system-ui, sans-serif; overflow: hidden;')
        # Advanced Cinematic CSS
        ui.add_head_html(f"""
            <style>
                @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');
                
                :root {{
                    --primary: {PRIMARY_COLOR};
                    --success: {ACCENT_COLOR};
                    --bg: {BG_COLOR};
                    --surface: #380036;
                    --text: {TEXT_HIGH};
                    --text-muted: {TEXT_MED};
                }}

                .cyber-panel {{
                    background: #380036 !important;
                    backdrop-filter: blur(20px);
                    border: 1px solid rgba(255, 255, 255, 0.05) !important;
                    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
                }}
                
                .cyber-border-l {{ border-left: 2px solid var(--primary); }}
                .cyber-border-r {{ border-right: 2px solid var(--primary); }}
                
                .glow-text {{
                    text-shadow: 0 0 10px rgba(222, 110, 75, 0.5);
                }}
                
                .scroll-hidden::-webkit-scrollbar {{ display: none; }}
                
                .telemetry-bar {{
                    background: rgba(26, 0, 26, 0.8);
                    border-top: 1px solid rgba(255,255,255,0.05);
                }}
                
                .nav-icon-btn i {{ color: white !important; }}
                .nav-icon-btn {{
                    transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                }}
                .nav-icon-btn:hover {{
                    box-shadow: 0 0 15px var(--primary);
                    transform: scale(1.1);
                }}
                .nav-icon-btn.active {{
                    color: var(--primary) !important;
                    background: rgba(222, 110, 75, 0.1) !important;
                }}
                .nav-icon-btn.active i {{ color: var(--primary) !important; }}

                .cam-card {{
                    position: relative;
                    overflow: hidden;
                    border-radius: 4px !important;
                    border: 1px solid rgba(255,255,255,0.03) !important;
                    background: #380036 !important;
                }}
                .cam-card:hover {{
                    border-color: var(--primary) !important;
                }}
                
                .intel-item {{
                    border-left: 2px solid rgba(255,255,255,0.05);
                    transition: background 0.3s;
                    border-radius: 0 8px 8px 0;
                }}
                .intel-item:hover {{
                    background: rgba(255,255,255,0.02);
                }}

                .scanline {{
                    width: 100%;
                    height: 100px;
                    z-index: 5;
                    background: linear-gradient(0deg, rgba(0, 0, 0, 0) 0%, rgba(222, 110, 75, 0.1) 50%, rgba(0, 0, 0, 0) 100%);
                    opacity: 0.1;
                    position: absolute;
                    bottom: 100%;
                    pointer-events: none;
                    animation: scanline 6s linear infinite;
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
                _NAV = [('grid_view', 0), ('person_add', 1), ('analytics', 2), ('settings', 3)]
                for icon, idx in _NAV:
                    btn = ui.button(icon=icon, on_click=lambda i=idx: self.switch_view(i)).props('flat round').classes('nav-icon-btn text-gray-400')
                    self.nav_btns[idx] = btn
                self.nav_btns[0].classes('active')
                
                ui.space()
                self.health_icon = ui.icon('sensors', color='white').style('font-size: 18px;')

            # 2. ACTIVITY INTELLIGENCE (Left Panel)
            with ui.column().classes('w-72 h-full p-0 cyber-panel border-r border-white/5'):
                ui.label("ACTIVITY LOG").classes('w-full px-6 py-4 text-[10px] font-black tracking-[4px] border-b border-white/5 opacity-50')
                self.log_container = ui.column().classes('w-full grow p-4 gap-3 overflow-y-auto scroll-hidden')
                # Populate some initial log placeholders
                with self.log_container:
                    self._add_log_entry("SYSTEM", "NETWORK SECURE", "green")
                    self._add_log_entry("WATCHDOG", "SCANNER ONLINE", "blue")

            # 3. MAIN COMMAND GRID (Central Zone)
            with ui.column().classes('grow h-full p-0 relative'):
                # Header Overlay
                with ui.row().classes('w-full px-8 py-4 items-center justify-between z-10 telemetry-bar'):
                    with ui.row().classes('items-center gap-4'):
                        ui.label("RYUK COMMAND CENTER").classes('font-black text-xs tracking-[5px] glow-text')
                        ui.badge("STABLE").props('color=green-9 size=xs').classes('text-[8px] px-2')
                    with ui.row().classes('items-center gap-6'):
                        self.clock_label = ui.label().classes('font-mono text-[11px] font-bold opacity-80')
                        ui.icon('public', size='xs', color='white').classes('opacity-30')
                
                # Dynamic Panels
                with ui.tab_panels(ui.tabs().set_visibility(False), value=0).classes('w-full grow bg-transparent z-0') as self.panels:
                    # -- Tab 0: High-Tech Grid --
                    with ui.tab_panel(0).classes('p-6 bg-transparent'):
                        self.grid = ui.grid(columns=2).classes('w-full gap-6')
                        with ui.column().classes('w-full items-center justify-center py-40 gap-4') as self.empty_container:
                            ui.icon('radar', size='48px', color='white').classes('animate-pulse opacity-10')
                            ui.label("OPTIMIZING SIGNAL...").classes('font-black tracking-[4px] text-[10px] opacity-20')
                        self.empty_label = self.empty_container

                    # -- Tab 1: Enrollment --
                    with ui.tab_panel(1).classes('p-12 bg-transparent'):
                        self._build_enrollment_view()

                    # -- Tab 2: Registry --
                    with ui.tab_panel(2).classes('p-12 bg-transparent'):
                        self._build_registry_view()

                    # -- Tab 3: Settings --
                    with ui.tab_panel(3).classes('p-12 bg-transparent'):
                        ui.label("CORE SETTINGS").classes('text-2xl font-black mb-4')
                        ui.label("Under construction...").classes('opacity-50')

                # Bottom Dashboard Info
                with ui.row().classes('w-full px-8 py-3 items-center justify-between telemetry-bar'):
                    with ui.row().classes('items-center gap-4'):
                        self.redis_status = ui.label("SRV-REDIS").classes('text-[9px] font-black tracking-widest')
                        self.mongo_status = ui.label("SRV-MONGO").classes('text-[9px] font-black tracking-widest')
                    with ui.row().classes('items-center gap-2'):
                        ui.label("LATENCY").classes('text-[8px] opacity-40')
                        ui.label("12ms").classes('text-[9px] font-mono text-green-500')

            # 4. TACTICAL RECOGNITION (Right Panel)
            with ui.column().classes('w-80 h-full p-0 cyber-panel border-l border-white/5'):
                ui.label("RECOGNITION FEED").classes('w-full px-6 py-4 text-[10px] font-black tracking-[4px] border-b border-white/5 opacity-50')
                self.intel_container = ui.column().classes('w-full grow p-4 gap-4 overflow-y-auto scroll-hidden')
                with self.intel_container:
                    self.no_intel_label = ui.label("SYSTEM READY. NO TARGETS DETECTED.").classes('w-full text-center py-10 text-[9px] opacity-20 font-bold tracking-widest')

    def _add_log_entry(self, source, message, color):
        with self.log_container:
            with ui.row().classes('w-full no-wrap gap-3 intel-item p-2'):
                ui.label(datetime.now().strftime("%H:%M:%S")).classes('text-[8px] font-mono opacity-30 mt-1')
                with ui.column().classes('gap-0'):
                    log_color = PRIMARY_COLOR if color in ['red', 'orange'] else ACCENT_COLOR if color == 'green' else TEXT_MED
                    ui.label(source).classes('text-[8px] font-black tracking-widest').style(f'color: {log_color}')
                    ui.label(message).classes('text-[10px] opacity-80 leading-tight')

    def _build_enrollment_view(self):
        with ui.column().classes('w-full max-w-4xl mx-auto gap-10'):
            ui.label("BIOMETRIC ACCESS REGISTRATION").classes('text-xl font-black tracking-[2px] glow-text')
            with ui.row().classes('w-full gap-10 items-start'):
                with ui.card().classes('w-64 h-64 cyber-panel p-0 flex items-center justify-center relative border-outline') as self.photo_card:
                    self.photo_preview = ui.image('').classes('absolute inset-0 w-full h-full object-cover opacity-80')
                    ui.icon('fingerprint', size='xl', color='white').classes('opacity-10')
                    ui.element('div').classes('scanline')
                    self.upload_ctrl = ui.upload(on_upload=self._handle_upload, label="", auto_upload=True).classes('absolute bottom-0 w-full opacity-10 hover:opacity-100 transition-opacity').props('flat dark')
                
                with ui.column().classes('grow gap-6'):
                    with ui.grid(columns=2).classes('w-full gap-4'):
                        self.enroll_name = ui.input(label="SUBJECT NAME").props('dark standout square').classes('w-full')
                        self.enroll_aadhar = ui.input(label="IDENTIFICATION ID").props('dark standout square').classes('w-full')
                        self.enroll_phone = ui.input(label="COMMUNICATION").props('dark standout square').classes('w-full')
                        self.enroll_address = ui.input(label="LOCATION DATA").props('dark standout square').classes('w-full')
                    self.enroll_threat = ui.select(['Low', 'Medium', 'High'], value='Low', label="THREAT PROFILING").props('dark standout square').classes('w-full')
                    self.enroll_btn = ui.button("EXECUTE ENROLLMENT", on_click=self._submit_enrollment).classes('w-full h-14 font-black tracking-[2px]').style('background-color: #380036; border: 1px solid rgba(255,255,255,0.1);')

    def _build_registry_view(self):
        with ui.row().classes('w-full justify-between items-center mb-6'):
            ui.label("CENTRAL INTELLIGENCE").classes('text-xl font-black tracking-[2px] glow-text')
            self.ci_count = ui.badge("0 IDENTITIES").props('color=white outline').classes('px-3 py-1 font-black text-[10px]')
        self.ci_search = ui.input(placeholder="TYPE TO SEARCH IDENTITIES...", on_change=self._filter_ci).classes('w-full mb-6 cyber-panel p-2 px-4').props('dark borderless')
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
        
        # Priority: Show all active streams first, then fill up to 4 with offline DB cameras
        active_list = sorted([cid for cid in active_cids])
        offline_list = sorted([cid for cid in db_cids if cid not in active_cids])
        
        to_show = active_list + offline_list
        limit = max(4, len(active_list))
        to_show = to_show[:limit]
        
        # Remove cards no longer in the restricted list
        for cid in list(self.camera_cards.keys()):
            if cid not in to_show:
                card = self.camera_cards.pop(cid)
                self.grid.remove(card)
        
        # Ensure all required cards exist and are in the correct order
        for idx, cid in enumerate(to_show):
            is_active = cid in active_cids
            if cid not in self.camera_cards:
                self._create_camera_card(cid, is_active)
            
            card = self.camera_cards[cid]
            # Ensure index stability in the grid
            try:
                if list(self.grid).index(card) != idx:
                    card.move(self.grid, idx)
            except ValueError:
                # If card somehow not in list(grid), re-create or just ignore for this cycle
                pass
            
            # Manage AI sessions back-end
            if is_active and cid not in active_sessions:
                self._start_session(cid)
            elif not is_active and cid in active_sessions:
                self._stop_session(cid)
                
    def _create_camera_card(self, client_id: str, active: bool):
        with self.grid:
            with ui.card().classes('w-full p-0 cyber-panel overflow-hidden cam-card') as card:
                card.client_id = client_id
                with ui.element('div').classes('w-full aspect-video relative bg-black/40 flex items-center justify-center') as container:
                    card.container = container
                    card.stream_img = ui.html('').classes('w-full h-full')
                    card.stream_img.set_visibility(False)
                    card.placeholder = ui.icon('videocam_off', size='64px', color='white').classes('opacity-10')
                    ui.element('div').classes('scanline')
                    
                    # Overlays
                    with ui.row().classes('absolute top-3 left-3 items-center gap-2'):
                        card.rec_dot = ui.label("REC").classes('text-[8px] font-black text-red-500 animate-pulse')
                        card.rec_dot.set_visibility(False)
                        ui.label(client_id.upper()).classes('text-[8px] font-black tracking-[2px] opacity-70')
                
                with ui.row().classes('w-full items-center p-3 px-4'):
                    card.status_label = ui.label("SIGNAL OFFLINE").classes('text-[8px] font-black tracking-widest text-red-500')
                    ui.space()
                    card.meta_label = ui.label("SEARCHING...").classes('text-[8px] font-mono opacity-30')
        
        self.camera_cards[client_id] = card
        self.empty_label.set_visibility(False)

    def _start_session(self, client_id: str):
        global active_sessions
        if client_id in active_sessions: return
        
        print(f"DEBUG: Starting Dashboard Session for CID: {client_id}")
        proc = Processor(client_id)
        # Thread-safe task submission via queue
        proc.on_detection = lambda meta: self.ui_queue.put(lambda: self._handle_detection(meta))
        proc.on_stream_start = lambda cid: self.ui_queue.put(lambda: self._handle_stream_actual_start(cid))
        proc.on_inactive = lambda cid: self.ui_queue.put(lambda: self._stop_session(cid))
        proc.start()
        active_sessions[client_id] = proc
        
        # Initial status change to show we are trying to connect
        if client_id in self.camera_cards:
            self.camera_cards[client_id].status_label.set_text("TUNING SIGNAL...")
            self.camera_cards[client_id].status_label.classes(replace='text-red-500', add='text-orange-500')

    def _process_ui_queue(self):
        """Processes pending UI tasks from the thread-safe queue on the main thread."""
        while not self.ui_queue.empty():
            try:
                task = self.ui_queue.get_nowait()
                task()
            except Exception as e:
                print(f"UI Queue Error: {e}")

    def _handle_stream_actual_start(self, client_id: str):
        # Safety check: if card is no longer in camera_cards (e.g., removed during transition)
        if client_id not in self.camera_cards:
            return

        # This runs when the first frame is RECEIVED by the processor
        if client_id in self.camera_cards:
            card = self.camera_cards[client_id]
            if not card.stream_img: return
            
            card.stream_img.content = f'<img src="/stream/{client_id}?t={time.time()}" style="width:100%; height:100%; object-fit:cover; width:100%; height:100%">'
            card.stream_img.set_visibility(True)
            card.placeholder.set_visibility(False)
            card.rec_dot.set_visibility(True)
            card.status_label.set_text("SIGNAL ACTIVE")
            card.status_label.classes(replace='text-red-500 text-orange-500', add='text-green-500')
            card.meta_label.set_text("1080p // 30fps")
        
        self._add_log_entry("SIGNAL", f"STREAM LIVE: {client_id}", "green")

    async def _handle_signal_drop(self, client_id: str):
        # We wrap this in an async function so it can be scheduled on the main loop
        if client_id in active_sessions:
            self._stop_session(client_id)

    def _stop_session(self, client_id: str):
        global active_sessions
        print(f"NiceGUI: Stopping session {client_id}")
        proc = active_sessions.pop(client_id, None)
        if proc:
            proc.stop()
        
        # UI Updates
        if client_id in self.camera_cards:
            card = self.camera_cards[client_id]
            card.stream_img.content = '<img src="" style="display:none;">'
            card.placeholder.set_visibility(True)
            card.rec_dot.set_visibility(False)
            card.status_label.set_text("OFFLINE")
            card.status_label.classes(replace='text-green-500', add='text-red-500')
            card.meta_label.set_text("NO SIGNAL")
        
        self._add_log_entry("SIGNAL", f"CONNECTION LOST: {client_id}", "red")

    def _handle_detection(self, metadata: dict):
        aadhar = metadata.get("aadhar")
        if not aadhar: return
        self.intel_last_seen[aadhar] = time.time()
        
        if aadhar not in self.intel_cards:
            self.intel_cards[aadhar] = metadata
            with self.intel_container:
                self.no_intel_label.set_visibility(False)
                threat = metadata.get('threat_level', 'Low')
                threat_color = 'red' if threat == 'High' else 'orange' if threat == 'Medium' else '#53DE53'
                with ui.row().classes('w-full no-wrap gap-4 intel-item p-3 border-r border-white/5 shadow-xl animate-fade').style('background: rgba(255,255,255,0.02)'):
                    ui.avatar('person', color='transparent').classes('border border-white/10').style('background-color: #380036; color: white')
                    with ui.column().classes('gap-0 grow'):
                        ui.label(metadata.get('name', 'Unknown')).classes('font-black text-xs tracking-wider')
                        ui.label(aadhar).classes('text-[8px] font-mono opacity-40')
                        with ui.row().classes('items-center gap-2 mt-2'):
                            ui.badge(threat.upper()).props(f'color={threat_color} size=xs').classes('text-[7px] px-2')
                    ui.label("MATCH 98.4%").classes('text-[8px] font-black opacity-30')
            
            # Add to activity log too
            self._add_log_entry("RECOGNITION", f"Target identified: {metadata.get('name')}", "orange")

    def _cleanup_intel(self):
        now = time.time()
        stale = [a for a, t in self.intel_last_seen.items() if now - t > INTEL_CLEANUP_S]
        for aadhar in stale:
            self.intel_last_seen.pop(aadhar)
            self.intel_cards.pop(aadhar)
            # We don't necessarily remove from container in this view, 
            # maybe just fade them out or keep a history? 
            # For this redesign, let's keep the most recent 10.
            if len(list(self.intel_container)) > 10:
                self.intel_container.remove(list(self.intel_container)[0])
        
        if not self.intel_cards and len(list(self.intel_container)) == 0:
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

    def _check_health(self):
        # Redis
        try:
            cache.ping(); self.redis_healthy = True
        except: self.redis_healthy = False
        
        # Mongo
        try:
            db = get_sync_db()
            if db is not None: db.command("ping"); self.mongo_healthy = True
            else: self.mongo_healthy = False
        except: self.mongo_healthy = False
        
        # Success = ACCENT_COLOR (#315C2B), Error = PRIMARY_COLOR (#DE6E4B)
        self.redis_status.style(f'color: {ACCENT_COLOR if self.redis_healthy else PRIMARY_COLOR}')
        self.mongo_status.style(f'color: {ACCENT_COLOR if self.mongo_healthy else PRIMARY_COLOR}')
        self.health_icon.style(f'color: {ACCENT_COLOR if self.redis_healthy and self.mongo_healthy else PRIMARY_COLOR}')

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
            # Run in thread to avoid blocking the event loop
            await asyncio.to_thread(
                enroll_face,
                temp_path, aadhar, name, threat, phone, address
            )
            
            # Cleanup temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            ui.notify(f"Identity {name} successfully enrolled.", type='positive')
            
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
                            ui.label(p.get('aadhar', '')).classes('text-[9px] font-mono opacity-40')
                            if p.get('phone'):
                                ui.label(p.get('phone')).classes('text-[8px] opacity-40 italic mt-1')

                    with ui.row().classes('items-center gap-6'):
                        # Threat Indicator
                        threat = p.get('threat_level', 'Low')
                        threat_color = 'red' if threat == 'High' else 'orange' if threat == 'Medium' else '#53DE53'
                        ui.badge(threat.upper()).props(f'color={threat_color} size=xs').classes('text-[7px] px-2 font-bold')
                        
                        # Actions
                        with ui.row().classes('gap-1'):
                            ui.button(icon='analytics', on_click=lambda p=p: self._show_tracking(p)).props('flat round size=sm').classes('opacity-30 hover:opacity-100')
                            ui.button(icon='edit', on_click=lambda p=p: self._edit_ci(p)).props('flat round size=sm').classes('opacity-30 hover:opacity-100')
                            ui.button(icon='delete', on_click=lambda p=p: self._delete_ci(p['aadhar'])).props('flat round size=sm').classes('opacity-30 hover:opacity-100 text-terracotta')

    def _filter_ci(self):
        self._load_ci()

    def _delete_ci(self, aadhar: str):
        delete_profile(aadhar)
        self._load_ci()
        ui.notify("Target purged from central registry.", type='warning')

    def _edit_ci(self, profile: dict):
        with ui.dialog().classes('p-0') as dialog, ui.card().classes('w-[500px] cyber-panel p-8 gap-6'):
            ui.label("MODERATING NEURAL PROFILE").classes('text-lg font-black tracking-widest mb-2 glow-text')
            
            name_input = ui.input(label="NAME", value=profile.get('name')).props('dark standout square').classes('w-full')
            phone_input = ui.input(label="COMMUNICATION", value=profile.get('phone')).props('dark standout square').classes('w-full')
            address_input = ui.input(label="LOCATION DATA", value=profile.get('address')).props('dark standout square').classes('w-full')
            threat_input = ui.select(['Low', 'Medium', 'High'], value=profile.get('threat_level', 'Low'), label="THREAT PROFILING").props('dark standout square').classes('w-full')
            
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
                ui.button("SAVE UPDATES", on_click=save).classes('px-6 font-black').style('background-color: #380036;')
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
                                
                                ui.label(loc.upper()).classes('text-[10px] font-black tracking-wider text-blue-400')
                                ui.label(log.get('client_id')).classes('text-[8px] opacity-30 font-mono')
                            ui.label(log.get('date_str')).classes('text-[9px] font-mono opacity-50')
        dialog.open()

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
            if count % 100 == 0:
                print(f"DEBUG: MJPEG Generator — Serving Frame {count} for {client_id} ({len(frame)} bytes)")
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        await asyncio.sleep(0.04) # ~25 FPS for smoothness

@app.get('/stream/{client_id}')
async def stream_endpoint(client_id: str):
    global active_sessions
    if client_id not in active_sessions:
        return Response(status_code=404)
    return StreamingResponse(mjpeg_generator(client_id), media_type='multipart/x-mixed-replace; boundary=frame')

def run_nicegui():
    ui.run(title="Ryuk AI", dark=True, reload=False, port=SERVER_PORT, show=False)

if __name__ in {"__main__", "__mp_main__"}:
    run_nicegui()
