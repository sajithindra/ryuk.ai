"""
ui/nice_components/widgets/intel_panel_item.py
Modular IntelPanelItem widget for NiceGUI.
"""
from nicegui import ui
from ui.styles import SURFACE_COLOR, get_threat_color

class IntelPanelItem(ui.row):
    def __init__(self, metadata: dict):
        super().__init__()
        self.classes('w-full no-wrap gap-4 intel-item p-3 border-r border-white/5 shadow-xl animate-fade cursor-pointer')
        self.style('background: rgba(255,255,255,0.02)')
        
        is_alpr = "plate_number" in metadata or "plate" in metadata
        icon = 'directions_car' if is_alpr else 'person'
        title = metadata.get('plate_number') or metadata.get('plate') or metadata.get('name', 'Unknown')
        subtitle = metadata.get('camera_id') or metadata.get('source', '')
        
        # All children MUST be inside `with self:` to nest properly
        with self:
            ui.avatar(icon, color='transparent').classes('border border-white/10').style(f'background-color: {SURFACE_COLOR}; color: white')
            with ui.column().classes('gap-0 grow'):
                ui.label(title).classes('font-black text-xs')
                self.source_label = ui.label(subtitle).classes('text-[10px] font-mono opacity-40')
                if not is_alpr:
                    threat = metadata.get('threat_level', 'Low')
                    threat_color = get_threat_color(threat)
                    with ui.row().classes('items-center gap-2 mt-1'):
                        self.threat_badge = ui.badge(threat.upper()).props(f'color={threat_color} size=xs').classes('text-[10px] px-2')
                else:
                    ui.label(metadata.get('source', '')).classes('text-[8px] opacity-20 uppercase font-bold')
            
            with ui.column().classes('items-end gap-1 shrink-0'):
                self.count_label = ui.label("×1").classes('text-[13px] font-black text-orange-500 opacity-80')
                self.time_label = ui.label("just now").classes('text-[10px] font-bold opacity-20')
    
    def update_count(self, count: int, camera: str = None):
        self.count_label.set_text(f"×{count}")
        self.time_label.set_text("just now")
        if camera:
            self.source_label.set_text(camera)
