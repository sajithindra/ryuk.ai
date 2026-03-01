"""
ui/widgets/enrollment_worker.py
Background QThread for face enrolment so the UI stays responsive.
"""
from PyQt6.QtCore import QThread, pyqtSignal
import core.watchdog_indexer as watchdog


class EnrollmentWorker(QThread):
    """Runs enroll_face + FAISS rebuild off the main thread."""
    success = pyqtSignal(str)
    error   = pyqtSignal(str)

    def __init__(self, image_path: str, aadhar: str, name: str,
                 threat: str, phone: str, address: str):
        super().__init__()
        self.image_path = image_path
        self.aadhar     = aadhar
        self.name       = name
        self.threat     = threat
        self.phone      = phone
        self.address    = address

    def run(self):
        try:
            watchdog.enroll_face(
                self.image_path, self.aadhar, self.name,
                self.threat, self.phone, self.address,
            )
            self.success.emit(
                f"Success: {self.name} is now globally recognized as {self.threat} threat."
            )
        except Exception as e:
            self.error.emit(str(e))
