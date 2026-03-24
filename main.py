import os
import sys
import time
import socket
import logging
import subprocess

# Suppress harmless uvicorn/asyncio shutdown tracebacks (CancelledError, WouldBlock)
class _ShutdownFilter(logging.Filter):
    _suppress = (
        'asyncio.exceptions.CancelledError',
        'anyio.WouldBlock',
        'Exception in ASGI application',
    )
    def filter(self, record):
        msg = record.getMessage()
        return not any(s in msg for s in self._suppress)

for _name in ('uvicorn.error', 'uvicorn.access', 'uvicorn'):
    logging.getLogger(_name).addFilter(_ShutdownFilter())

# Add current directory to sys.path for proper relative imports in child processes
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import SERVER_PORT, MONGO_URI, DB_NAME

# ---------------------------------------------------------------------------
# GLOBAL BOOTSTRAP: Managed Library Paths (TensorRT/CUDA)
# ---------------------------------------------------------------------------
def _bootstrap():
    """Heavy initialization within a controlled scope to avoid process pollution."""
    print("* Ryuk AI — NiceGUI Terminal Starting", flush=True)
    
    # 1. Environment cleanup for GPU libraries
    tensorrt_path = "/tmp/pip-install-5_vpsqas/onnxruntime-gpu_f68a5293444445889601f016599b4d00/onnxruntime/capi/lib"
    if tensorrt_path not in os.environ.get("LD_LIBRARY_PATH", ""):
        os.environ["LD_LIBRARY_PATH"] = f"{tensorrt_path}:{os.environ.get('LD_LIBRARY_PATH', '')}"
    
    # 2. Lazy Import UI components to prevent early NiceGUI initialization
    import ui.nice_gui
    return ui.nice_gui

# ---------------------------------------------------------------------------
# LAN IP DETECTION
# ---------------------------------------------------------------------------
def get_lan_ip():
    """Detects the current LAN IP for terminal display."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not need to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Core Process Initialization
    ng_ui = _bootstrap()
    lan_ip = get_lan_ip()

    # 2. Start the Background Manager process
    # This process handles UnifiedEngine and Sink, keeping main.py focused on UI.
    env = os.environ.copy()
    manager_proc = subprocess.Popen(
        [sys.executable, "/home/sajithindra/Projects/ryuk.ai/services/manager.py"],
        env=env
    )

    # 3. Launch the Dashboard
    print(f"============================================================", flush=True)
    print(f" RYUK AI DASHBOARD", flush=True)
    print(f" STATUS: Operational", flush=True)
    print(f" INTERFACE: http://{lan_ip}:{SERVER_PORT}", flush=True)
    print(f" SERVICE BIND: 0.0.0.0:{SERVER_PORT}", flush=True)
    print(f"============================================================", flush=True)

    try:
        # IMPORTANT: We use ng_ui.ui.run because ng_ui is the module containing the 'ui' object.
        ng_ui.ui.run(
            host='0.0.0.0',
            port=SERVER_PORT,
            title='Ryuk AI Dashboard',
            dark=True,
            reload=False,
            show=False,
            uvicorn_logging_level='warning'  # Suppress routine request logs on shutdown
        )
    except KeyboardInterrupt:
        print("\n* Signal Received: Terminating services...")
    finally:
        # Ignore any further Ctrl+C during cleanup
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        
        manager_proc.terminate()
        try:
            manager_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            manager_proc.kill()
        
        print("* Ryuk AI — Shutdown Complete.")
        # Hard-exit: skips pymongo/uvloop atexit cleanup races that produce
        # "Event loop is closed" / thread join tracebacks on repeated Ctrl+C
        os._exit(0)

