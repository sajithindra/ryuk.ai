import socket
import sys
import threading
from PyQt6.QtWidgets import QApplication
import qdarktheme

from core.server import run_server
from ui.dashboard import DashboardWindow

if __name__ == "__main__":
    # Get local IP for display
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()

    print("*" * 50)
    print(f"* Server running at: ws://{IP}:8000/ws/stream")
    print("*" * 50)

    # Start the FastAPI server via Uvicorn in a background thread
    server_thread = threading.Thread(target=run_server, args=(IP,), daemon=True)
    server_thread.start()

    # Create and run the PyQt6 Dashboard
    qt_app = QApplication(sys.argv)
    
    # Apply global dark theme using qdarktheme
    qt_app.setStyleSheet(qdarktheme.load_stylesheet("dark"))

    dashboard = DashboardWindow(IP)
    dashboard.show()
    
    sys.exit(qt_app.exec())
