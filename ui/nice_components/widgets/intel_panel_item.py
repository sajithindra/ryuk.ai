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
        
        aadhar = metadata.get("aadhar", "Unknown")
        threat = metadata.get('threat_level', 'Low')
        threat_color = get_threat_color(threat)
        camera = metadata.get('source', '')
        name = metadata.get('name', 'Unknown')
        
        # All children MUST be inside `with self:` to nest properly
        with self:
            ui.avatar('person', color='transparent').classes('border border-white/10').style(f'background-color: {SURFACE_COLOR}; color: white')
            with ui.column().classes('gap-0 grow'):
                self.name_label = ui.label(name).classes('font-black text-xs uppercase')
                self.source_label = ui.label(camera).classes('text-[10px] font-mono opacity-40')
                with ui.row().classes('items-center gap-2 mt-1'):
                    self.threat_badge = ui.badge(threat.upper()).props(f'color={threat_color} size=xs').classes('text-[10px] px-2')
            
            with ui.column().classes('items-end gap-1 shrink-0'):
                self.time_label = ui.label("just now").classes('text-[10px] font-bold opacity-30 tracking-wider uppercase')
    
    def update_metadata(self, metadata: dict):
        """Syncs the latest identity metadata (threat level, name, source)."""
        name = metadata.get('name', 'Unknown')
        camera = metadata.get('source', '')
        threat = metadata.get('threat_level', 'Low')
        threat_color = get_threat_color(threat)
        
        # In-place updates to avoid recreating layout
        self.name_label.set_text(name)
        self.time_label.set_text("just now")
        self.source_label.set_text(camera)
        
        # Update badge
        self.threat_badge.set_text(threat.upper())
        self.threat_badge.props(f'color={threat_color}')
