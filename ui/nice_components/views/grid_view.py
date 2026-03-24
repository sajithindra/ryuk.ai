"""
ui/nice_components/views/grid_view.py
Command Grid View for NiceGUI.
"""
from nicegui import ui
from ui.nice_components.widgets.camera_card import CameraCard

class GridView(ui.tab_panel):
    def __init__(self, on_add_camera, on_fullscreen, on_delete_camera):
        super().__init__('cameras')
        self.classes('p-6 bg-transparent')
        self.on_add_camera = on_add_camera
        self.on_fullscreen = on_fullscreen
        self.on_delete_camera = on_delete_camera
        
        self._add_card = None
        
        self.cameras = {} # Track active CameraCard objects
        
        with self:
            self.grid = ui.grid(columns=2).classes('w-full gap-6')
            self.empty_container = ui.column().classes('w-full items-center justify-center py-40 gap-4')
            with self.empty_container:
                ui.icon('radar', size='48px', color='white').classes('animate-pulse opacity-10')
                ui.label("Optimizing signal...").classes('font-black tracking-[2px] text-[13px] opacity-20')
        
    def create_camera_card(self, client_id: str):
        if client_id in self.cameras:
            return self.cameras[client_id]
            
        with self.grid:
            card = CameraCard(client_id, self.on_fullscreen, self.on_delete_camera)
            self.cameras[client_id] = card
        
        # Ensure "Add Camera" card stays at the end
        if self._add_card:
            self._add_card.move(self.grid)
            
        self.empty_container.set_visibility(False)
        return card

    def remove_camera(self, client_id: str):
        """Removes the camera card from the UI grid."""
        if client_id in self.cameras:
            card = self.cameras.pop(client_id)
            self.grid.remove(card)
            
            # Show empty state if no cameras left
            if not self.cameras:
                self.empty_container.set_visibility(True)

    def create_add_card(self):
        if self._add_card: return self._add_card
        
        with self.grid:
            self._add_card = ui.element('div').classes('w-full aspect-video cyber-panel overflow-hidden cam-card flex flex-col items-center justify-center border-dashed border-2 opacity-40 hover:opacity-100 transition-all cursor-pointer relative group')
            with self._add_card:
                self._add_card.on('click', self.on_add_camera)
                ui.icon('add_a_photo', size='64px', color='white').classes('opacity-10 group-hover:scale-110 transition-transform')
                ui.label("LINK NEW SIGNAL").classes('font-black tracking-[3px] text-[11px] opacity-20 mt-4 group-hover:opacity-60')
                ui.element('div').classes('scanline opacity-10')
        return self._add_card
    def add_camera(self, client_id: str):
        """Alias for create_camera_card to match NiceDashboard calls."""
        return self.create_camera_card(client_id)
