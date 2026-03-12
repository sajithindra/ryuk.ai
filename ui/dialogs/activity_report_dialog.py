"""
ui/dialogs/activity_report_dialog.py
Chronological activity logs + AI tactical dossier via Gemini.
"""
import os
import base64
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QComboBox, QTextEdit, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtGui import QPageLayout
from PyQt6.QtCore import QMarginsF

import core.watchdog_indexer as watchdog


class DossierWorker(QThread):
    progress_update    = pyqtSignal(str)
    chunk_received     = pyqtSignal(str)
    finished_generation = pyqtSignal()
    error_occurred     = pyqtSignal(str)

    def __init__(self, meta: dict, timeframe_label: str):
        super().__init__()
        self.meta            = meta
        self.timeframe_label = timeframe_label

    def run(self):
        try:
            self.progress_update.emit("> Booting Ryuk Intelligence Core…")
            self.msleep(600)
            self.progress_update.emit(f"> Requesting telemetry for: {self.timeframe_label}…")
            days_ago = {"Today": 1, "Last 7 Days": 7}.get(self.timeframe_label)
            logs = watchdog.get_activity_report(self.meta["aadhar"], limit=150, days_ago=days_ago)
            self.progress_update.emit(f"> Extracted {len(logs)} MongoDB records.")
            self.msleep(400)
            self.progress_update.emit("> Transmitting to Gemini…")
            self.msleep(800)
            from core.agent import ryuk_agent
            self.progress_update.emit("STREAM_START")
            for chunk in ryuk_agent.generate_dossier_stream(self.meta, logs, self.timeframe_label):
                self.chunk_received.emit(chunk)
            self.finished_generation.emit()
        except Exception as e:
            self.error_occurred.emit(str(e))


class ActivityReportDialog(QMainWindow):
    """Chronological movement logs + streaming AI dossier generation."""

    def __init__(self, meta: dict, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setWindowTitle(f"TACTICAL INTELLIGENCE | {meta.get('name','').upper()}")
        self.setFixedSize(900, 700)
        self.setStyleSheet("""
            QMainWindow { background-color: #0F111A; }
            QLabel { color: #F8FAFC; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        ml = QHBoxLayout(central)
        ml.setContentsMargins(20, 20, 20, 20)
        ml.setSpacing(20)

        # Left: log timeline
        left = QVBoxLayout()
        lbl_hdr = QLabel("CHRONOLOGICAL LOGS")
        lbl_hdr.setStyleSheet("color: #94A3B8; font-weight: 700; font-size: 12px; margin-bottom: 10px;")
        left.addWidget(lbl_hdr)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedWidth(350)
        cont = QWidget()
        self.list_layout = QVBoxLayout(cont)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(cont)
        left.addWidget(self.scroll)

        # Right: AI dossier
        right = QVBoxLayout()
        ah = QHBoxLayout()
        ai_hdr = QLabel("AI TACTICAL DOSSIER")
        ai_hdr.setStyleSheet("color: #94A3B8; font-weight: 700; font-size: 12px;")
        self.timeframe_cb = QComboBox()
        self.timeframe_cb.addItems(["All Time", "Today", "Last 7 Days"])
        ah.addWidget(ai_hdr); ah.addWidget(self.timeframe_cb)
        right.addLayout(ah)

        self.btn_gen = QPushButton("GENERATE DOSSIER")
        self.btn_gen.setStyleSheet("""
            QPushButton { background: #3B82F6; color: #FFFFFF; font-weight: 600; padding: 10px; border-radius: 6px; border: none; }
            QPushButton:hover { background: #2563EB; }
        """)
        self.btn_gen.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_gen.clicked.connect(self._generate)

        self.btn_pdf = QPushButton("DOWNLOAD PDF")
        self.btn_pdf.setStyleSheet("""
            QPushButton { background: #10B981; color: #FFFFFF; font-weight: 600; padding: 10px; border-radius: 6px; border: none; }
            QPushButton:hover { background: #059669; }
        """)
        self.btn_pdf.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pdf.clicked.connect(self._download_pdf)
        self.btn_pdf.hide()

        bl = QHBoxLayout(); bl.addWidget(self.btn_gen); bl.addWidget(self.btn_pdf)
        right.addLayout(bl)

        self.report_view = QTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setStyleSheet(
            "background: #0F111A; border: 1px solid #1E293B; border-radius: 8px;"
            "padding: 15px; color: #CBD5E1; font-size: 13px;"
        )
        self.report_view.setPlaceholderText(
            "Awaiting command. Select a timeframe and generate the intelligence dossier."
        )
        right.addWidget(self.report_view)

        ml.addLayout(left)
        ml.addLayout(right, 1)

        self._current_dossier = ""
        self._load_logs()

    def _load_logs(self):
        logs = watchdog.get_activity_report(self.meta["aadhar"])
        if not logs:
            lbl = QLabel("No activity recorded.")
            lbl.setStyleSheet("color: #475569; font-size: 12px; font-style: italic;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_layout.addWidget(lbl)
            return
        for log in logs:
            row = QFrame()
            rl = QVBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(2)
            locs = log.get("locations", ["Unknown", "Unknown"])
            for txt, style in [
                (log.get("date_str", "?"), "color: #3B82F6; font-weight: 600; font-size: 11px;"),
                (f"📍 {locs[0]} ➔ {locs[1]}", "color: #F8FAFC; font-size: 12px;"),
                (f"DEVICE: {log.get('client_id','?')}", "color: #475569; font-size: 10px;"),
            ]:
                l = QLabel(txt); l.setStyleSheet(style); rl.addWidget(l)
            self.list_layout.addWidget(row)

    def _generate(self):
        self.btn_gen.setText("SYNTHESIZING…"); self.btn_gen.setDisabled(True)
        self.report_view.setPlainText("Ryuk Terminal initialized.\n")
        self.worker = DossierWorker(self.meta, self.timeframe_cb.currentText())
        self.worker.progress_update.connect(self._on_progress)
        self.worker.chunk_received.connect(self._on_chunk)
        self.worker.finished_generation.connect(self._on_done)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, msg: str):
        if msg == "STREAM_START": self.report_view.clear(); self._current_dossier = ""
        else: self.report_view.append(msg)

    def _on_chunk(self, chunk: str):
        self._current_dossier += chunk
        self.report_view.setMarkdown(self._current_dossier)

    def _on_done(self):
        self.btn_gen.setText("GENERATE DOSSIER"); self.btn_gen.setDisabled(False)
        self.btn_pdf.show()

    def _on_error(self, err: str):
        self.report_view.append(f"\n[!] ERROR: {err}")
        self.btn_gen.setText("GENERATE DOSSIER"); self.btn_gen.setDisabled(False)
        self.btn_pdf.hide()

    def _download_pdf(self):
        name   = self.meta.get("name", "unknown").lower().replace(" ", "_")
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
        default = os.path.join(os.path.expanduser("~"), "Downloads",
                               f"ryuk_dossier_{name}_{ts}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Save Dossier", default, "PDF Files (*.pdf)")
        if path:
            try:
                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                printer.setOutputFileName(path)
                printer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
                self.report_view.document().print(printer)
                QMessageBox.information(self, "Export Complete", f"Saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", str(e))
