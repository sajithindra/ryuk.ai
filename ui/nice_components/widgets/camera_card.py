"""
ui/nice_components/widgets/camera_card.py
Modular CameraCard widget for NiceGUI.
"""
from nicegui import ui
import urllib.parse

class CameraCard(ui.element):
    def __init__(self, client_id: str, on_fullscreen, on_delete):
        super().__init__('div')
        self.classes('w-full p-0 cyber-panel overflow-hidden cam-card group relative aspect-video')
        self.client_id = client_id
        
        with self:
            self.stream_img = ui.interactive_image().classes('absolute inset-0 w-full h-full object-cover z-0 transition-opacity duration-1000')
            self.stream_img.set_visibility(False)
            
            # Background/Placeholder
            with ui.element('div').classes('absolute inset-0 flex items-center justify-center bg-black/40 z-10'):
                self.placeholder = ui.icon('videocam_off', size='64px', color='white').classes('opacity-10')
            
            ui.element('div').classes('scanline z-20')
            
            # Interactive Layer (Top)
            with ui.element('div').classes('absolute inset-0 z-30'):
                # Fullscreen Button (Tactical Yellow - Bottom Right)
                self.fs_btn = ui.button(icon='fullscreen', on_click=lambda: on_fullscreen(client_id)) \
                    .props('flat round size=md') \
                    .classes('absolute bottom-3 right-3 transition-all shadow-lg group-hover:opacity-100 opacity-60') \
                    .style('color: #FFD100 !important;')
                
                # Delete Button (Top Right)
                self.del_btn = ui.button(icon='delete', on_click=lambda: on_delete(client_id)) \
                    .props('flat round size=md color=red') \
                    .classes('absolute top-3 right-3 transition-all opacity-0 group-hover:opacity-100') \
                    .style('background: rgba(0,0,0,0.4);')
                with self.del_btn:
                    ui.tooltip('DELETE CAMERA NODE').classes('bg-red-900/90 font-mono text-[10px]')
                
                # Overlays
                with ui.row().classes('absolute top-3 left-3 items-center gap-2 pointer-events-none'):
                    self.rec_dot = ui.label("REC").classes('text-[11px] font-black text-red-500 animate-pulse')
                    self.device_tooltip_el = ui.element('div').classes('w-4 h-4')
                    with self.device_tooltip_el:
                        self.tooltip = ui.tooltip("Loading device info...").classes('bg-black/90 text-blue-300 font-mono text-[12px]')
                
                # Metadata Overlay (Bottom) — camera name always visible, detections on hover
                with ui.column().classes('absolute bottom-4 left-4 gap-0 pointer-events-none'):
                    self.status_label_overlay = ui.label(client_id).classes('text-[11px] font-black tracking-widest text-white/60 uppercase')
                    self.meta_label_overlay = ui.label("").classes('text-[10px] font-mono text-green-400 opacity-0 transition-opacity duration-500')
    
    def update_stream(self, started: bool):
        self.stream_img.set_visibility(started)
        self.placeholder.set_visibility(not started)
        if started:
            encoded_cid = urllib.parse.quote(self.client_id)
            self.stream_img.set_source(f"/stream/{encoded_cid}")
            self.stream_img.classes(remove='opacity-0', add='opacity-100')
        # camera name stays shown regardless

    def update_metadata(self, text: str):
        """Show detected name(s) under the camera label."""
        self.meta_label_overlay.set_text(text)
        self.meta_label_overlay.classes(remove='opacity-0', add='opacity-100')
