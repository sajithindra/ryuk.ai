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

print("Bootstrap completed, continuing with imports")

# ============================================================================
# Normal imports — GPU libs are now resolvable by the dynamic linker
# ============================================================================
import time
import numpy as np

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.watchdog_indexer as watchdog
from core.state import cache
from config import FAISS_THRESHOLD
import core.serialization as serde

def run_search_service():
    print("=" * 60)
    print("RYUK AI — FAISS SEARCH SERVICE")
    print("=" * 60)
    
    # WatchdogIndexer is already initialized as a singleton in the module
    print("\n[READY] Waiting for embedding stream ('ryuk:embed')...")
    
    last_index_version = None
    
    while True:
        try:
            # 1. Check for Index Sync
            try:
                current_version = cache.get("ryuk:index:version")
                if current_version != last_index_version:
                    if last_index_version is not None:
                         print(f"INFO: Index update signal received (v: {current_version}). Rebuilding...")
                         watchdog.update_faiss_index()
                    last_index_version = current_version
            except Exception as e:
                print(f"DEBUG: Failed to check index version: {e}")

            # 2. Process data
            packed = cache.blpop("ryuk:embed", timeout=1)
            if not packed:
                continue
            
            _, data = packed
            
            if data is None or not isinstance(data, bytes):
                print(f"Invalid data: {data}, skipping")
                continue
            
            packet = serde.unpack(data)
            if not packet:
                continue
                
            faces = packet.get('faces', [])
            client_id = packet.get('client_id')
            
            if not faces:
                # No faces to search, pass through
                cache.rpush("ryuk:faiss", serde.pack(packet))
                continue
                
            start_time = time.time()
            
            results = []
            for face in faces:
                # Handle face as a dict (unpacked from msgpack)
                emb = face.get('embedding')
                if emb is None:
                    print(f"DEBUG SEARCH: Face missing embedding! Available keys: {face.keys()}")
                    results.append({"name": "Unknown", "threat_level": "Low"})
                    continue
                
                context = {
                    "pose": face.get("pose", [0, 0, 0]),
                    "norm": face.get("norm", float(np.linalg.norm(emb)))
                }
                res = watchdog.recognize_face(emb, threshold=FAISS_THRESHOLD, context=context)
                
                results.append(res if res else {"name": "Unknown", "threat_level": "Low"})

            latency = (time.time() - start_time) * 1000
            
            # Update packet
            packet['search_results'] = results
            packet['search_latency'] = latency
            packet['search_timestamp'] = time.time()
            
            # Push to Sink Service
            cache.rpush("ryuk:faiss", serde.pack(packet))
            
            if packet.get('frame_count', 0) % 50 == 0:
                print(f"PERF: Searched {len(faces)} faces for {client_id} | Latency: {latency:.2f}ms")
                
        except Exception as e:
            print(f"ERROR in Search Service: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)

if __name__ == "__main__":
    try:
        run_search_service()
    except KeyboardInterrupt:
        print("\nStopping Search Service...")
