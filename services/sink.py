import os
import sys

# ============================================================================
# GPU BOOTSTRAP — Must run before any ONNX/InsightFace/CUDA import.
# cuDNN 9.19.1 is installed at /usr/lib/x86_64-linux-gnu but may not be in
# the active LD_LIBRARY_PATH depending on the shell environment.
# We also include the venv nvidia packages as a secondary source.
# ============================================================================
def _bootstrap():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
import time
import json

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.watchdog_indexer as watchdog
from core.state import cache, cache_str
from config import ALERT_COOLDOWN_S, LOG_COOLDOWN_S
import core.serialization as serde

def run_sink_service():
    print("=" * 60)
    print("RYUK AI — SINK SERVICE (LOGGING & ALERTER)")
    print("=" * 60)
    
    print("\n[READY] Waiting for FAISS stream ('ryuk:faiss')...")
    
    while True:
        try:
            packed = cache.blpop("ryuk:faiss", timeout=1)
            if not packed:
                continue
            
            _, data = packed
            packet = serde.unpack(data)
            
            if not packet:
                continue
            
            search_results = packet.get('search_results', [])
            client_id = packet.get('client_id')
            
            if not search_results:
                # No faces identified, still push the packet for UI to clear boxes
                cache.set(f"stream:{client_id}:results", serde.pack(packet), ex=5)
                continue
                
            start_time = time.time()
            
            for i, res in enumerate(search_results):
                if not res or 'name' not in res:
                    continue
                
                name = res.get('name', 'Unknown')
                threat = res.get('threat_level', 'Low')
                aadhar = res.get('aadhar')
                
                if aadhar and name != "Unknown":
                    # 1. Activity Logging (with cooldown)
                    lock_key = f"log_lock:{aadhar}:{client_id}"
                    if not cache_str.get(lock_key):
                        watchdog.log_activity(aadhar, client_id)
                        cache_str.set(lock_key, "1", ex=int(LOG_COOLDOWN_S))
                        
                    # 2. Auto-Augmentation (Frontal face update)
                    faces = packet.get('faces', [])
                    if i < len(faces):
                        face_obj = faces[i]
                        pose = face_obj.get("pose", [0, 0, 0])
                        # If pose is stable (near zero), augment
                        if all(abs(angle) < 15 for angle in pose):
                            aug_lock = f"aug_lock:{aadhar}"
                            if not cache_str.get(aug_lock):
                                watchdog.augment_identity(aadhar, face_obj.get('embedding'))
                                cache_str.set(aug_lock, "1", ex=3600)
                
                # 3. Security Alerts
                if threat == "High":
                    alert_lock = f"alert_lock:{name}:{client_id}"
                    if not cache_str.get(alert_lock):
                        msg = json.dumps({
                            "type":      "SECURITY_ALERT",
                            "message":   f"High Security Alert: {name} spotted at {client_id}",
                            "name":      name,
                            "source":    client_id,
                            "timestamp": time.time(),
                        })
                        cache.publish("security_alerts", msg)
                        cache_str.set(alert_lock, "1", ex=int(ALERT_COOLDOWN_S))

            res_key = f"stream:{client_id}:results"
            cache.set(res_key, serde.pack(packet), ex=5)
            
            if packet.get('frame_count', 0) % 50 == 0:
                print(f"SINK: Finished processing {client_id} | Faces: {len(search_results)}")
                
        except Exception as e:
            print(f"ERROR in Sink Service: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)

if __name__ == "__main__":
    try:
        run_sink_service()
    except KeyboardInterrupt:
        print("\nStopping Sink Service...")
