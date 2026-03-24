"""
ui/nice_components/widgets/identity_card.py
NiceGUI widget for displaying subject profiles in the Registry view.
"""
from nicegui import ui
from ui.styles import SURFACE_COLOR, get_threat_color

class IdentityCard(ui.card):
    def __init__(self, profile: dict, on_logs=None, on_edit=None, on_delete=None):
        super().__init__()
        self.classes('w-full p-0 cyber-panel overflow-hidden profile-card group')
        self.style('background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05)')
        
        name        = profile.get('name', 'Unknown Target').upper()
        aadhar      = profile.get('aadhar', 'N/A')
        threat      = profile.get('threat_level', 'Low')
        threat_color = get_threat_color(threat)
        thumb       = profile.get('photo_thumb', '')
        
        with self:
            with ui.grid(columns='100px 1fr').classes('w-full p-4 gap-6 items-start'):
                # ── Left: Portrait Thumbnail ────────────────────────────
                with ui.element('div').classes('relative rounded-xl border border-white/10 overflow-hidden bg-black/40 shadow-2xl').style('width:100px; height:120px'):
                    if thumb:
                        try:
                            src = f'data:image/jpeg;base64,{thumb}' if not thumb.startswith('data:') else thumb
                            ui.image(src).classes('w-full h-full object-cover')
                        except Exception:
                            ui.icon('person', size='lg').classes('absolute-center opacity-10')
                    else:
                        ui.icon('person', size='lg').classes('absolute-center opacity-10')
                    
                    # Scanning effect on photo
                    ui.element('div').classes('scanline absolute inset-0 z-10 opacity-30 pointer-events-none')

                # ── Right: Details Grid ──────────────────────────────────
                with ui.column().classes('grow gap-2 min-w-0'):
                    with ui.row().classes('w-full justify-between items-start no-wrap'):
                        with ui.column().classes('gap-0'):
                            ui.label(name).classes('text-[15px] font-black text-white leading-tight truncate')
                            ui.label(f"ID: {aadhar}").classes('text-[10px] font-mono opacity-40 font-bold')
                        
                        ui.badge(threat.upper()).props(f'color={threat_color} size=sm').classes('text-[9px] font-black px-3 py-1 rounded-sm shadow-lg')

                    # Additional info grid
                    with ui.grid(columns=2).classes('w-full gap-x-4 gap-y-1 mt-1 opacity-60'):
                        self._field_item("Phone", profile.get('phone', 'N/A'))
                        self._field_item("Source", profile.get('source', 'MANUAL'))
                    
                    if profile.get('notes'):
                        ui.label(profile['notes']).classes('text-[10px] italic opacity-30 mt-1 truncate max-w-full')

                    # ── Bottom: Integrated Actions ──────────────────────
                    with ui.row().classes('w-full justify-end gap-1 mt-2 opacity-0 group-hover:opacity-100 transition-opacity'):
                        if on_logs:
                            ui.button(icon='history', on_click=lambda a=aadhar: on_logs(a)).props('flat round size=sm color=blue').tooltip('Activity')
                        if on_edit:
                            ui.button(icon='edit', on_click=lambda p=profile: on_edit(p)).props('flat round size=sm color=gray').tooltip('Edit')
                        if on_delete:
                            ui.button(icon='delete', on_click=lambda a=aadhar: on_delete(a)).props('flat round size=sm color=red').tooltip('Delete')

    def _field_item(self, label, value):
        with ui.column().classes('gap-0'):
            ui.label(label).classes('text-[8px] font-black tracking-widest opacity-40 uppercase')
            ui.label(str(value)).classes('text-[10px] font-bold truncate')
