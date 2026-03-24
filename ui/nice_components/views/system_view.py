"""
ui/nice_components/views/system_view.py
System Diagnostics View for NiceGUI.
"""
from nicegui import ui
import platform
from ui.styles import ERROR_COLOR, SUCCESS_COLOR, PRIMARY_COLOR, TEXT_MED

class SystemView(ui.tab_panel):
    def __init__(self, server_port: int, ip_address: str = "127.0.0.1"):
        super().__init__('system')
        self.classes('p-12 bg-transparent')
        
        with self:
            with ui.column().classes('w-full max-w-5xl mx-auto gap-8'):
                ui.label("System diagnostics").classes('text-3xl font-black tracking-[2px] glow-text mb-2')
                
                with ui.grid(columns=3).classes('w-full gap-6'):
                    # OS & Host Info
                    with ui.card().classes('cyber-panel p-6 gap-4'):
                        ui.label("OS & KERNEL").classes('text-[12px] font-black opacity-40 tracking-widest')
                        uname = platform.uname()
                        with ui.column().classes('gap-2 w-full'):
                            self._info_row("System", uname.system)
                            self._info_row("Node", uname.node)
                            self._info_row("LAN IP", ip_address)
                            self._info_row("Machine", uname.machine)

                    # Resource Inventory
                    with ui.card().classes('cyber-panel p-6 gap-4'):
                        ui.label("RESOURCE INVENTORY").classes('text-[12px] font-black opacity-40 tracking-widest')
                        with ui.column().classes('gap-2 w-full'):
                           self.sys_total_procs = self._info_row("Total Processes", "0")
                           self.sys_total_threads = self._info_row("Total Threads", "0")
                           self.sys_load_avg = self._info_row("Load Average", "0.0, 0.0, 0.0")

                    # GPU Details (NVIDIA)
                    with ui.card().classes('cyber-panel p-6 gap-4'):
                        ui.label("NVIDIA GPU ENGINE").classes('text-[12px] font-black opacity-40 tracking-widest')
                        with ui.column().classes('gap-2 w-full'):
                            self.sys_gpu_name = self._info_row("Model", "Detecting...")
                            with ui.row().classes('w-full justify-between items-center no-wrap'):
                                ui.label("Utilization").classes('text-[13px] opacity-60 font-medium')
                                self.sys_gpu_util_pct = ui.label("0%").classes('text-[12px] font-bold text-blue-300')
                            self.sys_gpu_bar = ui.linear_progress(value=0, show_value=False).classes('w-full h-1').props('color=blue-400')
                            
                            self.sys_vram_usage = self._info_row("VRAM Usage", "0MB / 0MB")

                # Ryuk Services & DB Status
                with ui.row().classes('w-full gap-6 no-wrap'):
                    # Core Services
                    with ui.card().classes('grow cyber-panel p-6 gap-4'):
                        ui.label("RYUK CORE SERVICES").classes('text-[12px] font-black opacity-40 tracking-widest')
                        with ui.grid(columns=3).classes('w-full gap-4'):
                            with ui.column().classes('stat-box items-center'):
                                ui.label("AI ENGINE").classes('stat-label')
                                self.svc_engine_status = ui.label("OFFLINE").classes('stat-value').style(f'color: {ERROR_COLOR}')
                                self.svc_engine_metrics = ui.label("0% CPU • 0MB").classes('text-[10px] opacity-40 font-mono mt-1')
                            with ui.column().classes('stat-box items-center'):
                                ui.label("DATA SINK").classes('stat-label')
                                self.svc_sink_status = ui.label("OFFLINE").classes('stat-value').style(f'color: {ERROR_COLOR}')
                                self.svc_sink_metrics = ui.label("0% CPU • 0MB").classes('text-[10px] opacity-40 font-mono mt-1')
                            with ui.column().classes('stat-box items-center'):
                                ui.label("DATABASE").classes('stat-label')
                                with ui.row().classes('items-center gap-2 mt-1'):
                                    self.db_mongo_status = ui.icon('database', color='red', size='14px')
                                    ui.label("MONGO").classes('text-[10px] opacity-60 font-black')
                                with ui.row().classes('items-center gap-2'):
                                    self.db_redis_status = ui.icon('bolt', color='red', size='14px')
                                    ui.label("REDIS").classes('text-[10px] opacity-60 font-black')
                                
                    # WS Server Details
                    with ui.card().classes('w-80 cyber-panel p-6 gap-4'):
                        ui.label("WS STREAM SERVER").classes('text-[12px] font-black opacity-40 tracking-widest')
                        with ui.column().classes('gap-2 w-full'):
                            ui.label(f"ws://{ip_address}:{server_port}/api/ws/stream").classes('text-[10px] font-mono opacity-40 break-all mb-2')
                            self.ws_active_streams = self._info_row("Active Streams", "0")
                            self.ws_subscribers = self._info_row("Alert Subs", "0")
                            self.ws_status = ui.label("RECEPTION ACTIVE").classes('text-[10px] font-black text-green-500 tracking-widest uppercase mt-2')

                # GPU Processes Table
                with ui.card().classes('w-full cyber-panel p-6 gap-4'):
                    ui.label("GPU WORKLOAD (PER PROCESS)").classes('text-[12px] font-black opacity-40 tracking-widest')
                    self.gpu_process_container = ui.column().classes('w-full gap-2')
                    with self.gpu_process_container:
                        ui.label("No active GPU processes detected.").classes('text-[13px] opacity-20 italic py-4')

                # Network Info
                with ui.card().classes('w-full cyber-panel p-6 gap-4'):
                    ui.label("NETWORK & CONNECTIVITY").classes('text-[12px] font-black opacity-40 tracking-widest')
                    with ui.row().classes('w-full justify-between items-center'):
                        with ui.column().classes('gap-2 grow'):
                            self.sys_ping = self._info_row("Latency (Gateway)", "Calculating...")
                            self.sys_net_up = self._info_row("Total Sent", "0 MB")
                            self.sys_net_down = self._info_row("Total Received", "0 MB")
                        
                        ui.icon('lan', size='64px').classes('opacity-10 mr-10')

    def _info_row(self, label, value):
        with ui.row().classes('w-full justify-between items-center no-wrap'):
            ui.label(label).classes('text-[13px] opacity-60 font-medium')
            val_label = ui.label(value).classes('text-[14px] font-bold font-mono text-blue-300')
            return val_label
