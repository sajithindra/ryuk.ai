"""
ui/views/ci_view.py
Central Intelligence — scrollable list of registered identities
with live search and count badge.
"""
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QWidget, QMessageBox,
)
from PyQt6.QtCore import Qt

import core.watchdog_indexer as watchdog
from ui.widgets.profile_row import ProfileRow


class CIView(QFrame):
    """Searchable list of all enrolled identities in the registry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentArea")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(0)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("CENTRAL INTELLIGENCE")
        title.setStyleSheet("color: #F8FAFC; font-size: 18px; font-weight: 700;")
        self.count_badge = QLabel("0 IDENTITIES")
        self.count_badge.setStyleSheet("""
            color: #10B981; background: rgba(16,185,129,0.1);
            border-radius: 4px; padding: 4px 12px; font-size: 10px; font-weight: 600;
        """)
        hdr.addWidget(title)
        hdr.addSpacing(12)
        hdr.addWidget(self.count_badge)
        hdr.addStretch()
        outer.addLayout(hdr)
        outer.addSpacing(16)

        # Search bar
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name or ID…")
        self.search.textChanged.connect(self._filter)
        outer.addWidget(self.search)
        outer.addSpacing(16)

        # Scrollable list
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._list_layout.setSpacing(10)
        self._scroll.setWidget(self._list_container)
        outer.addWidget(self._scroll, 1)

    # ------------------------------------------------------------------
    # Public API (called by DashboardWindow)
    # ------------------------------------------------------------------

    def load(self):
        """Fetch all profiles from DB, rebuild list, update count badge."""
        # Clear
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        profiles = watchdog.get_all_profiles()
        for p in profiles:
            row = ProfileRow(
                p,
                on_edit=lambda checked=False, meta=p: self._edit(meta),
                on_history=lambda checked=False, meta=p: self._history(meta),
                on_delete=lambda checked=False, uid=p["aadhar"]: self._delete(uid),
            )
            self._list_layout.addWidget(row)

        n = len(profiles)
        self.count_badge.setText(f"{n} {'IDENTITY' if n == 1 else 'IDENTITIES'}")

    # ------------------------------------------------------------------
    # Private handlers
    # ------------------------------------------------------------------

    def _filter(self, query: str):
        query = query.lower().strip()
        for i in range(self._list_layout.count()):
            w = self._list_layout.itemAt(i).widget()
            if w:
                match = (query in w.meta.get("name", "").lower() or
                         query in w.meta.get("aadhar", "").lower())
                w.setVisible(match)

    def _history(self, meta: dict):
        from ui.dialogs.activity_report_dialog import ActivityReportDialog
        self._dialog = ActivityReportDialog(meta, self)
        self._dialog.show()

    def _edit(self, meta: dict):
        from ui.dialogs.edit_profile_dialog import EditProfileDialog
        self._edit_dlg = EditProfileDialog(meta, self)
        self._edit_dlg.destroyed.connect(self.load)
        self._edit_dlg.show()

    def _delete(self, aadhar: str):
        reply = QMessageBox.question(
            self, "Security Clearance",
            f"Permanently delete profile {aadhar}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            watchdog.delete_profile(aadhar)
            self.load()
            QMessageBox.information(self, "Ryuk AI", "Target purged from central registry.")
