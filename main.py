import os
import sys
import socket
import threading
import subprocess
import atexit

# ============================================================================
# GPU BOOTSTRAP — Must run before any ONNX/InsightFace/CUDA import.
# cuDNN 9.19.1 is installed at /usr/lib/x86_64-linux-gnu but may not be in
# the active LD_LIBRARY_PATH depending on the shell environment.
# We also include the venv nvidia packages as a secondary source.
# ============================================================================
def _bootstrap():
    root = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.normpath(os.path.join(root, ".venv", "bin", "python3"))
    is_venv = hasattr(sys, 'real_prefix') or (sys.base_prefix != sys.prefix)
    
    # 1. Choose target executable (Prefer .venv)
    target_exe = venv_python if (not is_venv and os.path.exists(venv_python)) else sys.executable
    
    # 2. Build LD_LIBRARY_PATH for GPU
    candidate_dirs = []
    
    # Auto-discover all nvidia venv libs (cudnn, cublas, nvjitlink, etc.)
    # VENV LIBS FIRST to avoid system symbol conflicts (e.g. libnvJitLink)
    venv_site = os.path.join(root, ".venv", "lib", "python3.12", "site-packages")
    nvidia_root = os.path.join(venv_site, "nvidia")
    if os.path.isdir(nvidia_root):
        for sub in os.listdir(nvidia_root):
            lib_path = os.path.join(nvidia_root, sub, "lib")
            if os.path.isdir(lib_path):
                candidate_dirs.append(lib_path)
    
    # System libs LAST
    candidate_dirs.extend(["/usr/lib/x86_64-linux-gnu", "/usr/local/cuda/lib64"])
    current = os.environ.get("LD_LIBRARY_PATH", "")
    existing = set(current.split(":")) if current else set()
    additions = [d for d in candidate_dirs if os.path.isdir(d) and d not in existing]
    
    # 3. Restart if executable changed or environment needs update
    if (target_exe != sys.executable) or additions:
        if additions:
            os.environ["LD_LIBRARY_PATH"] = ":".join(additions) + ((":" + current) if current else "")
        # print(f"[*] Bootstrapping environment via {target_exe}")
        os.execv(target_exe, [target_exe] + sys.argv)

_bootstrap()

# ============================================================================
# Normal imports — GPU libs are now resolvable by the dynamic linker
# ============================================================================
from ui.nice_gui import run_nicegui
from config import SERVER_PORT

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
    print(f"* Ryuk AI — NiceGUI Terminal Starting")
    print(f"* Dashboard: http://localhost:{SERVER_PORT}")
    print(f"* Streaming API: ws://{IP}:{SERVER_PORT}/api/ws/stream")
    print("*" * 50)

    # 1. Start Background Services (Unified Engine & Sink)
    manager_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "services", "manager.py")
    print(f"[*] Launching background services via {manager_path}...")
    
    # We use subprocess.Popen to let it run in the background
    # It inherits the current environment (including LD_LIBRARY_PATH from bootstrap)
    svc_manager = subprocess.Popen([sys.executable, manager_path], 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.STDOUT,
                                   text=True,
                                   bufsize=1)
    
    # Optional: Small thread to pipe manager output to main log/console
    def pipe_output(proc):
        for line in proc.stdout:
            print(f"[MANAGER] {line.strip()}")
            
    threading.Thread(target=pipe_output, args=(svc_manager,), daemon=True).start()
    
    # Ensure services are killed on exit
    atexit.register(lambda: svc_manager.terminate())

    # 2. Run the Dashboard
    run_nicegui()
