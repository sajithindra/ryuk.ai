"""
ui/nice_components/views/enrollment_view.py
Enrollment View for NiceGUI — redesigned with photo upload zone and clean form.
"""
from nicegui import ui
from ui.styles import PRIMARY_COLOR

class EnrollmentView(ui.tab_panel):
    def __init__(self, on_upload, on_submit):
        super().__init__('enroll')
        self.classes('p-8 bg-transparent')

        with self:
            with ui.column().classes('w-full max-w-6xl mx-auto gap-10'):
                # ── Header ───────────────────────────────────────────
                with ui.column().classes('gap-1'):
                    with ui.row().classes('items-center gap-3'):
                        ui.element('div').classes('w-1.5 h-8 bg-gradient-to-b from-primary to-accent rounded-full')
                        ui.label("NEURAL IDENTITY REGISTRY").classes('text-4xl font-black tracking-tighter glow-text')
                    ui.label("Initialize biometric indexing and tactical classification metadata").classes('text-[14px] opacity-40 ml-4 font-medium uppercase tracking-widest')

                with ui.row().classes('w-full gap-8 items-start no-wrap'):
                    # ── Left: Biometric Capture ──────────────────────
                    with ui.card().classes('cyber-panel p-8 gap-6 shrink-0 shadow-2xl').style('width: 320px;'):
                        ui.label("BIOMETRIC CAPTURE").classes('text-[11px] font-black tracking-[3px] opacity-30 text-center w-full')

                        # Photo Zone (Click to Upload)
                        with ui.element('div').classes('relative overflow-hidden rounded-2xl border border-white/10 shadow-inner group cursor-pointer').style('width: 256px; height: 320px; background: rgba(0,0,0,0.6); margin: 0 auto;') \
                            .on('click', lambda: self.upload_ctrl.run_method('pickFiles')):
                            # Preview
                            self.photo_preview = ui.image('').classes('absolute inset-0 w-full h-full object-cover transition-all duration-700')
                            
                            # Overlay Grid
                            ui.element('div').classes('absolute inset-0 z-10 opacity-20 pointer-events-none').style('background-image: radial-gradient(circle, rgba(255,255,255,0.1) 1px, transparent 1px); background-size: 20px 20px;')
                            
                            # Default Visuals
                            with ui.element('div').classes('absolute inset-0 flex flex-col items-center justify-center gap-4 transition-opacity duration-500') as self._icon_overlay:
                                ui.icon('face_retouching_natural', size='80px').classes('opacity-10 group-hover:opacity-20 transition-opacity')
                                ui.label("DEPLOY PHOTO").classes('text-[11px] font-black tracking-[4px] opacity-20 group-hover:opacity-40 transition-opacity')
                            
                            # Animated Scanline (High Velocity)
                            ui.element('div').classes('scanline absolute inset-0 z-20 pointer-events-none opacity-40')
                            
                            # corners
                            ui.element('div').classes('absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-primary/40 rounded-tl-sm')
                            ui.element('div').classes('absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-primary/40 rounded-tr-sm')
                            ui.element('div').classes('absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 border-primary/40 rounded-bl-sm')
                            ui.element('div').classes('absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-primary/40 rounded-br-sm')

                            # Invisible Upload Controller (Triggered by pick_files)
                            # Invisible Upload Controller (Triggered by pick_files)
                            async def handle_upload(e):
                                await on_upload(e)
                                self._icon_overlay.set_visibility(False)

                            self.upload_ctrl = ui.upload(
                                on_upload=handle_upload,
                                label='',
                                auto_upload=True
                            ).classes('hidden').props('flat dark')

                        # Threat Pulse & Classification
                        with ui.column().classes('w-full gap-4 mt-2'):
                            self.enroll_threat = ui.select(
                                ['Low', 'Medium', 'High'],
                                value='Low',
                                label="THREAT ASSESSMENT"
                            ).props('dark standout square dense').classes('w-full font-bold')

                            with ui.row().classes('w-full items-center justify-between px-2'):
                                ui.label("SCAN STATUS").classes('text-[9px] font-black opacity-30 tracking-widest')
                                with ui.row().classes('items-center gap-2'):
                                    ui.element('div').classes('w-2 h-2 rounded-full bg-green-500 animate-pulse shadow-[0_0_10px_rgba(34,197,94,0.6)]')
                                    ui.label("READY").classes('text-[10px] font-black text-green-400')

                    # ── Right: Subject Metadata ──────────────────────
                    with ui.card().classes('grow cyber-panel p-8 gap-8 shadow-2xl'):
                        ui.label("TACTICAL METADATA").classes('text-[11px] font-black tracking-[3px] opacity-30')

                        with ui.grid(columns=2).classes('w-full gap-6'):
                            self.enroll_name   = ui.input(label="FULL NAME").props('dark standout square clearable').classes('w-full font-bold uppercase').style('letter-spacing: 0.5px')
                            self.enroll_aadhar = ui.input(label="IDENTIFICATION ID / AADHAR").props('dark standout square clearable mask="#### #### ####"').classes('w-full font-mono font-bold')
                            self.enroll_phone  = ui.input(label="COMMUNICATION CHANNEL").props('dark standout square clearable').classes('w-full font-mono')
                            self.role_select   = ui.select(
                                ["Personnel", "Visitor", "VIP", "Blacklist"],
                                value="Personnel",
                                label="SUBJECT CLASSIFICATION"
                            ).props('dark standout square').classes('w-full font-bold')
                        
                        self.enroll_address = ui.input(label="LOCATIONAL ANCHOR / ADDRESS").props('dark standout square').classes('w-full')
                        self.enroll_notes = ui.textarea(label="INTEL / OBSERVATIONAL NOTES").props('dark standout square').classes('w-full').style('min-height:100px')

                        # Divider & Status
                        with ui.column().classes('w-full gap-4 pt-4 border-t border-white/5'):
                            with ui.row().classes('w-full justify-between items-end'):
                                with ui.column().classes('gap-1'):
                                    ui.label("NEURAL COMMITMENT").classes('text-[10px] font-black opacity-30 tracking-widest')
                                    ui.label("ENSURE DATA INTEGRITY BEFORE INITIALIZATION").classes('text-[9px] opacity-20 italic')
                                
                                ui.button(
                                    "COMMIT TO INDEX",
                                    on_click=on_submit,
                                    icon='fingerprint'
                                ).classes('cyber-btn px-10 h-16 text-[14px] font-black tracking-[3px]').props('unelevated')

    def get_data(self):
        return {
            "name":         self.enroll_name.value,
            "aadhar":       self.enroll_aadhar.value,
            "phone":        self.enroll_phone.value,
            "address":      self.enroll_address.value,
            "role":         self.role_select.value,
            "threat_level": self.enroll_threat.value,
            "notes":        self.enroll_notes.value if hasattr(self, 'enroll_notes') else '',
        }

    def clear(self):
        self.enroll_name.value    = ""
        self.enroll_aadhar.value  = ""
        self.enroll_phone.value   = ""
        self.enroll_address.value = ""
        if hasattr(self, 'enroll_notes'):
            self.enroll_notes.value = ""
        self.photo_preview.set_source('')
        self._icon_overlay.set_visibility(True)
