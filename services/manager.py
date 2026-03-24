import subprocess
import time
import sys
import os
import signal

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

SERVICES = [
    "services/unified_engine.py",
    "services/sink.py"
]

def get_python_executable():
    # Get project root (one level up from services/manager.py)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Prefer .venv if it exists, otherwise fall back to current sys.executable
    venv_paths = [
        os.path.join(root, ".venv", "bin", "python3"),
        os.path.join(root, ".venv", "bin", "python"),
        os.path.join(root, "venv", "bin", "python3"),
        os.path.join(root, "venv", "bin", "python")
    ]
    for path in venv_paths:
        if os.path.exists(path):
            return path
    return sys.executable

def run_manager():
    processes = []
    python_exe = get_python_executable()
    
    print("=" * 60)
    print("RYUK AI — MICRO-PIPELINE MANAGER")
    print("=" * 60)
    print(f"[*] Using Python: {python_exe}")
    
    def signal_handler(sig, frame):
        print("\n[!] Shutdown signal received. Killing services...")
        for p in processes:
            p.terminate()
        
        # Give them 2 seconds to terminate gracefully, then kill
        start = time.time()
        while time.time() - start < 2:
            if all(p.poll() is not None for p in processes):
                break
            time.sleep(0.1)
            
        for p in processes:
            if p.poll() is None:
                p.kill()
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    
    # Build LD_LIBRARY_PATH for services
    candidate_dirs = []
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_site = os.path.join(root, ".venv", "lib", "python3.12", "site-packages")
    nvidia_root = os.path.join(venv_site, "nvidia")
    if os.path.isdir(nvidia_root):
        for sub in os.listdir(nvidia_root):
            lib_path = os.path.join(nvidia_root, sub, "lib")
            if os.path.isdir(lib_path):
                candidate_dirs.append(lib_path)
    
    # System libs LAST
    candidate_dirs.extend(["/usr/lib/x86_64-linux-gnu", "/usr/local/cuda/lib64"])
    
    env = os.environ.copy()
    current_ld = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = ":".join(candidate_dirs) + ((":" + current_ld) if current_ld else "")
    
    # Start all services
    for svc in SERVICES:
        abs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", svc)
        abs_path = os.path.normpath(abs_path)
        print(f"[*] Starting {svc}...")
        
        # Explicitly pass environment to ensure venv and LD_LIBRARY_PATH are inherited
        p = subprocess.Popen([python_exe, abs_path], env=env)
        processes.append(p)
        time.sleep(2) # Give some time for model loading
        
    print("\n[READY] All services are running. Press Ctrl+C to stop.")
    
    # Track which services we've already reported as dead to avoid spam
    dead_reported = [False] * len(SERVICES)
    
    try:
        while True:
            # Check if any process died
            for i, p in enumerate(processes):
                if p.poll() is not None and not dead_reported[i]:
                    print(f"[!] Service {SERVICES[i]} died unexpectedly (code {p.returncode})")
                    dead_reported[i] = True
            time.sleep(2)
    except Exception as e:
        print(f"Manager Error: {e}")
    finally:
        for p in processes:
            p.terminate()

if __name__ == "__main__":
    run_manager()
