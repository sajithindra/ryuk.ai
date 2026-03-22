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

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ============================================================================
# Normal imports — GPU libs are now resolvable by the dynamic linker
# ============================================================================
import time
import numpy as np
from core.ai_processor import GlobalAIProcessor
from core.state import cache
from config import MAX_INFERENCE_SIZE
import core.serialization as serde

def run_detection_service():
    print("=" * 60)
    print("RYUK AI — DETECTION SERVICE (GPU)")
    print("=" * 60)
    
    # Load ONLY detection model
    # We use det_size from config or default (640, 640)
    det_size = MAX_INFERENCE_SIZE if isinstance(MAX_INFERENCE_SIZE, tuple) else (MAX_INFERENCE_SIZE, MAX_INFERENCE_SIZE)
    processor = GlobalAIProcessor(det_size=det_size, models_to_load=['detection'], use_worker=False)
    det_model = processor.app.models['detection']
    
    print("\n[READY] Waiting for ingestion stream ('ryuk:ingest')...")
    
    while True:
        try:
            # BLPOP blocks until an item is available
            # Timeout of 1s to allow for clean shutdown if needed
            packed = cache.blpop("ryuk:ingest", timeout=1)
            if not packed:
                continue
            
            _, data = packed
            packet = serde.unpack(data)
            
            if not packet:
                continue
            
            frame = packet.get('frame')
            if frame is None:
                continue
                
            start_time = time.time()
            
            # Run Face Detection
            bboxes, kpss = det_model.detect(frame, max_num=0, metric='default')
            
            latency = (time.time() - start_time) * 1000
            
            # Update packet
            packet['bboxes'] = bboxes
            packet['kpss'] = kpss
            packet['det_latency'] = latency
            packet['det_timestamp'] = time.time()
            
            # Push to next stage
            cache.rpush("ryuk:detect", serde.pack(packet))
            
            # Optional: throttle/limit queue size if embedder is slow
            q_len = cache.llen("ryuk:detect")
            if q_len > 10:
                # If embedder is falling behind, we might want to warn
                # print(f"[WARN] Detection queue depth: {q_len}")
                pass
            
            # Log periodic status
            if packet.get('frame_count', 0) % 50 == 0:
                print(f"PERF: Processed {packet['client_id']} | Faces: {len(bboxes)} | Latency: {latency:.2f}ms")
                
        except Exception as e:
            print(f"ERROR in Detection Service: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1) # Backoff on error

if __name__ == "__main__":
    try:
        run_detection_service()
    except KeyboardInterrupt:
        print("\nStopping Detection Service...")
