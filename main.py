import os
import sys
import socket
import threading

# ============================================================================
# GPU BOOTSTRAP — Must run before any ONNX/InsightFace/CUDA import.
# cuDNN 9.19.1 is installed at /usr/lib/x86_64-linux-gnu but may not be in
# the active LD_LIBRARY_PATH depending on the shell environment.
# We also include the venv nvidia packages as a secondary source.
# ============================================================================
def _bootstrap_cuda_library_path():
    venv_site = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "venv", "lib", "python3.12", "site-packages"
    )
    candidate_dirs = [
        "/usr/lib/x86_64-linux-gnu",           # System cuDNN 9.19.1
        "/usr/local/cuda/lib64",               # CUDA toolkit libs
        "/usr/local/cuda-12.0/lib64",
        os.path.join(venv_site, "nvidia", "cudnn",         "lib"),
        os.path.join(venv_site, "nvidia", "cublas",        "lib"),
        os.path.join(venv_site, "nvidia", "cuda_runtime",  "lib"),
    ]
    current = os.environ.get("LD_LIBRARY_PATH", "")
    existing = set(current.split(":")) if current else set()
    additions = [d for d in candidate_dirs if os.path.isdir(d) and d not in existing]
    if additions:
        os.environ["LD_LIBRARY_PATH"] = ":".join(additions) + ((":" + current) if current else "")
        os.execv(sys.executable, [sys.executable] + sys.argv)

_bootstrap_cuda_library_path()

# ============================================================================
# Normal imports — GPU libs are now resolvable by the dynamic linker
# ============================================================================
from PyQt6.QtWidgets import QApplication
import qdarktheme

from core.server import run_server
from ui.dashboard import DashboardWindow

if __name__ == "__main__":
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

    server_thread = threading.Thread(target=run_server, args=(IP,), daemon=True)
    server_thread.start()

    qt_app = QApplication(sys.argv)
    qt_app.setStyleSheet(qdarktheme.load_stylesheet("dark"))

    dashboard = DashboardWindow(IP)
    dashboard.show()
    sys.exit(qt_app.exec())
