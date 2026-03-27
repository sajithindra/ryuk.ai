"""
ui/nice_components/widgets/intel_panel_item.py
Modular IntelPanelItem widget for NiceGUI.
"""
from nicegui import ui
from ui.styles import SURFACE_COLOR, get_threat_color

class IntelPanelItem(ui.column):
    def __init__(self, metadata: dict):
        super().__init__()
        self.classes('w-full gap-0 tactical-card p-0 mb-4 animate-fade')
        
        aadhar = metadata.get("aadhar", "Unknown")
        threat = metadata.get('threat_level', 'Low')
        threat_color = get_threat_color(threat)
        camera = metadata.get('source', 'INTERNAL_STATION')
        name = metadata.get('name', 'Unknown')
        
        with self:
            # 1. Header Row
            with ui.row().classes('w-full tactical-header justify-between items-center'):
                with ui.row().classes('items-center gap-2'):
                    ui.element('div').classes('status-dot')
                    ui.label(name).classes('font-black text-[12px] uppercase tracking-wider')
                
                ui.label(f"×{metadata.get('count', 1)}").classes('text-[13px] font-mono font-black text-primary')

            # 2. Main Body
            with ui.column().classes('px-4 py-3 gap-2'):
                with ui.row().classes('items-center gap-2'):
                    icon = 'category' if metadata.get('is_object') else 'person'
                    ui.icon(icon, size='14px').classes('opacity-40')
                    self.source_label = ui.label(camera).classes('text-[10px] font-mono opacity-60 uppercase tracking-widest')
                
                with ui.row().classes('items-center gap-2'):
                    ui.icon('security', size='14px').classes('opacity-40')
                    self.threat_badge = ui.badge(threat.upper()).props(f'color={threat_color} size=xs').classes('text-[9px] px-2 font-black rounded')
                
                self.time_label = ui.label("ACTIVE SESSION").classes('text-[8px] font-black tracking-widest opacity-20 mt-1 uppercase')

            # 3. Reinforcement Action Bar
            det_id = metadata.get('det_id')
            if det_id:
                with ui.row().classes('w-full border-t border-white/5 bg-white/[0.02] p-2 justify-between items-center px-4'):
                    ui.label("RL FEEDBACK").classes('text-[8px] font-black tracking-[3px] opacity-20')
                    with ui.row().classes('gap-1'):
                        with ui.button(on_click=lambda: self.emit_feedback(True)).props('flat dense size=sm').classes('px-2 hover:bg-positive/10 rounded group'):
                            with ui.row().classes('items-center gap-1'):
                                ui.icon('check', size='12px', color='positive').classes('group-hover:scale-110')
                                ui.label("YES").classes('text-[9px] font-bold text-positive')
                        
                        with ui.button(on_click=lambda: self.emit_feedback(False)).props('flat dense size=sm').classes('px-2 hover:bg-negative/10 rounded group'):
                            with ui.row().classes('items-center gap-1'):
                                ui.icon('close', size='12px', color='negative').classes('group-hover:scale-110')
                                ui.label("NO").classes('text-[9px] font-bold text-negative')

    def emit_feedback(self, is_correct: bool):
        """Bridge UI feedback to the AI engine."""
        if hasattr(self, 'on_feedback'):
            self.on_feedback(is_correct)
        ui.notify("FEEDBACK SUBMITTED" if is_correct else "CORRECTION LOGGED", 
                  type='positive' if is_correct else 'info',
                  position='bottom-right')
    
    def update_count(self, count: int, camera: str = None):
        if hasattr(self, 'count_label') and self.count_label:
            self.count_label.set_text(f"×{count}")
        self.time_label.set_text("just now")
        if camera:
            self.source_label.set_text(camera)
