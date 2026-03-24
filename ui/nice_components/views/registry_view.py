"""
ui/nice_components/views/registry_view.py
Registry View for NiceGUI.
"""
from nicegui import ui
from ui.nice_components.widgets.identity_card import IdentityCard

class RegistryView(ui.tab_panel):
    def __init__(self, on_search):
        super().__init__('registry')
        self.classes('p-8 bg-transparent content-start')
        
        # Callbacks wired in from NiceDashboard
        self.on_logs_cb = None
        self.on_edit_cb = None
        self.on_delete_cb = None
        
        with self:
            # Header + compact inline search
            with ui.row().classes('w-full justify-between items-center mb-6 gap-4'):
                with ui.column().classes('gap-0 shrink-0'):
                    ui.label("Identity Registry").classes('text-2xl font-black tracking-tight glow-text')
                    ui.label("Neural index of enrolled subjects").classes('text-[12px] opacity-50')
                
                with ui.row().classes('items-center gap-2 cyber-panel px-3 py-1 rounded-lg w-72'):
                    ui.icon('search', size='18px').classes('opacity-40 shrink-0')
                    self.ci_search = ui.input(placeholder="Search subjects...").classes('text-sm font-mono').props('dark borderless dense')
                    self.ci_search.on('input', on_search)
                
                self.ci_count = ui.badge("0 IDENTITIES").props('color=white outline').classes('px-3 py-1 font-black text-[11px] shrink-0')

            with ui.scroll_area().classes('w-full custom-scrollbar').style('height: calc(100vh - 220px)'):
                self.ci_list = ui.grid(columns=3).classes('w-full gap-6 pb-10')

    def set_callbacks(self, on_logs, on_edit, on_delete):
        self.on_logs_cb = on_logs
        self.on_edit_cb = on_edit
        self.on_delete_cb = on_delete

    def add_profile(self, profile_data: dict):
        with self.ci_list:
            IdentityCard(
                profile_data,
                on_logs=self.on_logs_cb,
                on_edit=self.on_edit_cb,
                on_delete=self.on_delete_cb,
            )
        self.update_count(len(self.ci_list.default_slot.children))

    def clear(self):
        self.ci_list.clear()
        self.update_count(0)

    def update_count(self, count: int):
        self.ci_count.set_text(f"{count} IDENTITIES")
