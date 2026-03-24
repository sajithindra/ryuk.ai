from nicegui import ui
from core.database import get_sync_db
from core.watchdog_indexer import delete_camera, register_camera_metadata
from ui.styles import BG_COLOR, TEXT_HIGH, PRIMARY_COLOR, ERROR_COLOR

class CameraMgmtView:
    def __init__(self):
        self.container = ui.column().classes('w-full h-full p-8 gap-8')
        self.refresh()

    def refresh(self):
        self.container.clear()
        with self.container:
            with ui.row().classes('w-full items-center justify-between'):
                ui.label("CAMERA MANAGEMENT").classes('text-2xl font-black glow-text')
                ui.button("REFRESH", icon='refresh', on_click=self.refresh).classes('cyber-btn-small')

            with ui.scroll_area().classes('w-full grow'):
                self.list_container = ui.column().classes('w-full gap-4')
                self._load_cameras()

    def _load_cameras(self):
        try:
            db = get_sync_db()
            if db is None: return
            cameras = list(db.cameras.find({}))
            
            if not cameras:
                with self.list_container:
                    ui.label("No cameras linked. Add one from the dashboard.").classes('opacity-30 italic')
                return

            for cam in cameras:
                self._add_camera_row(cam)
        except Exception as e:
            with self.list_container:
                ui.label(f"Error loading cameras: {e}").classes('text-red-500')

    def _add_camera_row(self, cam):
        cid = cam.get('client_id')
        name = cam.get('name', cid)
        url = cam.get('rtsp_url') or cam.get('source')
        sub_url = cam.get('substream_url', '')

        with self.list_container:
            with ui.card().classes('w-full p-6 cyber-panel border border-white/5 hover:border-primary/20'):
                with ui.row().classes('w-full items-center gap-6'):
                    # Icon/Avatar
                    with ui.element('div').classes('w-12 h-12 rounded bg-primary/10 flex items-center justify-center'):
                        ui.icon('videocam', color='primary', size='24px')
                    
                    # Info
                    with ui.column().classes('grow gap-0'):
                        ui.label(name).classes('text-lg font-black')
                        ui.label(cid).classes('text-[10px] font-mono opacity-40 uppercase tracking-tighter')
                        ui.label(url).classes('text-[11px] opacity-60 truncate max-w-md')
                    
                    # Actions
                    with ui.row().classes('items-center gap-2'):
                        ui.button(icon='history', on_click=lambda: self._show_activity(cid)).props('flat round color=white/30').tooltip('View Activity')
                        ui.button(icon='edit', on_click=lambda: self._edit_camera(cam)).props('flat round color=white/30').tooltip('Edit Details')
                        ui.button(icon='delete', on_click=lambda: self._delete_confirm(cid)).props('flat round color=red/50').tooltip('Delete Camera')

    def _show_activity(self, cid):
        from core.watchdog_indexer import get_activity_report
        # Get ALPR events for this camera too
        try:
            db = get_sync_db()
            alpr_events = list(db.alpr_events.find({"camera_id": cid}).sort("timestamp", -1).limit(50))
            face_events = get_activity_report(None, camera_id=cid, limit=50) # Assuming it supports camera_id filter
        except:
            alpr_events = []
            face_events = []

        with ui.dialog().classes('w-full') as dialog, ui.card().classes('w-full max-w-4xl h-[600px] cyber-panel p-0'):
            with ui.column().classes('w-full h-full gap-0'):
                with ui.row().classes('w-full p-6 items-center justify-between border-b border-white/10'):
                    ui.label(f"ACTIVITY LOG: {cid}").classes('font-black tracking-widest')
                    ui.button(icon='close', on_click=dialog.close).props('flat round dense')
                
                with ui.scroll_area().classes('w-full grow p-6'):
                    if not alpr_events and not face_events:
                        ui.label("No recent activity detected.").classes('opacity-20 italic py-10 text-center w-full')
                    
                    # Merge and sort events
                    all_events = []
                    for e in alpr_events:
                        all_events.append({
                            "type": "ALPR",
                            "time": e.get('timestamp'),
                            "title": f"Vehicle: {e.get('plate_number')}",
                            "desc": f"{e.get('vehicle_color', '')} {e.get('vehicle_type', 'Vehicle')}",
                            "conf": e.get('confidence', 0)
                        })
                    for e in face_events:
                        all_events.append({
                            "type": "FACE",
                            "time": e.get('timestamp'),
                            "title": f"Subject Identified",
                            "desc": e.get('name', 'Unknown Subject'),
                            "conf": e.get('confidence', 0)
                        })
                    
                    all_events.sort(key=lambda x: x['time'] if x['time'] else 0, reverse=True)
                    
                    for ev in all_events:
                        with ui.row().classes('w-full items-center gap-4 py-3 border-b border-white/5'):
                            ui.label(str(ev['time'])[11:19] if ev['time'] else "--:--").classes('text-xs font-mono opacity-40')
                            ui.label(ev['type']).classes('text-[10px] font-black px-2 py-0.5 bg-white/5 rounded text-primary/80')
                            with ui.column().classes('gap-0 grow'):
                                ui.label(ev['title']).classes('font-bold')
                                ui.label(ev['desc']).classes('text-xs opacity-50')
                            ui.label(f"{ev['conf']*100:.0f}%").classes('text-[10px] font-mono opacity-30')

        dialog.open()

    def _edit_camera(self, cam):
        cid = cam.get('client_id')
        name_val = cam.get('name', cid)
        url_val = cam.get('rtsp_url') or cam.get('source')
        sub_val = cam.get('substream_url', '')

        with ui.dialog() as dialog, ui.card().classes('cyber-panel p-8 min-w-[400px]'):
            ui.label(f"EDIT CAMERA: {cid}").classes('font-black mb-4')
            name_in = ui.input("Display Name", value=name_val).classes('w-full')
            url_in = ui.input("Main RTSP URL", value=url_val).classes('w-full')
            sub_in = ui.input("Substream URL", value=sub_val).classes('w-full')

            async def save():
                try:
                    register_camera_metadata(cid, ["Manual"], url_in.value, substream_url=sub_in.value, name=name_in.value)
                    ui.notify("Camera settings updated.", type='positive')
                    dialog.close()
                    self.refresh()
                except Exception as e:
                    ui.notify(f"Update failed: {e}", type='negative')

            with ui.row().classes('w-full justify-end mt-4'):
                ui.button("CANCEL", on_click=dialog.close).props('flat')
                ui.button("SAVE CHANGES", on_click=save).classes('cyber-btn-small')
        
        dialog.open()

    def _delete_confirm(self, cid):
        with ui.dialog() as dialog, ui.card().classes('cyber-panel p-8'):
            ui.label("DELETE CAMERA?").classes('font-black text-red-400')
            ui.label(f"This will unlink {cid} and stop all AI monitoring.").classes('text-sm opacity-60')
            
            async def do_delete():
                try:
                    delete_camera(cid)
                    ui.notify(f"Camera {cid} unlinked.", type='positive')
                    dialog.close()
                    self.refresh()
                except Exception as e:
                    ui.notify(f"Delete failed: {e}", type='negative')

            with ui.row().classes('w-full justify-end mt-4'):
                ui.button("CANCEL", on_click=dialog.close).props('flat')
                ui.button("DELETE", on_click=do_delete, color='red').props('flat')
        
        dialog.open()
