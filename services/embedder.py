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
import torch
import cv2
import numpy as np
from insightface.app.common import Face
from core.ai_processor import GlobalAIProcessor
from core.state import cache
import core.serialization as serde

def run_embedding_service():
    print("=" * 60)
    print("RYUK AI — EMBEDDING SERVICE (GPU)")
    print("=" * 60)
    
    # Load ONLY recognition model
    # Note: GlobalAIProcessor will still load detection by default unless pruned
    # But we want to ensure TorchFaceAligner is available on GPU.
    processor = GlobalAIProcessor(models_to_load=['recognition'], use_worker=False)
    rec_model = processor.app.models.get('recognition')
    if not rec_model:
        print("[ERROR] Recognition model not found!")
        return
        
    aligner = processor.aligner # TorchFaceAligner
    
    print("\n[READY] Waiting for detection stream ('ryuk:detect')...")
    
    while True:
        try:
            packed = cache.blpop("ryuk:detect", timeout=1)
            if not packed:
                continue
            
            _, data = packed
            packet = serde.unpack(data)
            
            if not packet:
                continue
            
            frame = packet.get('frame')
            bboxes = packet.get('bboxes')
            kpss = packet.get('kpss')
            person_bboxes = packet.get('person_bboxes', [])
            
            if frame is None:
                continue
            
            # If no faces skip
            if (bboxes is None or len(bboxes) == 0):
                packet['faces'] = []
                cache.rpush("ryuk:embed", serde.pack(packet))
                continue
                
            start_time = time.time()
            
            # 1. Create Face objects
            faces = []
            if bboxes is not None:
                for i in range(bboxes.shape[0]):
                    face = Face(bbox=bboxes[i, 0:4], kps=kpss[i] if kpss is not None else None, det_score=bboxes[i, 4])
                    faces.append(face)
            
            # 2. Batched Alignment on GPU
            with torch.no_grad():
                # frames_gpu: (B, 3, H, W)
                frame_gpu = torch.from_numpy(frame.copy()).to('cuda').permute(2, 0, 1).float().unsqueeze(0)
                # lms_gpu: (N, 5, 2)
                lms_gpu = torch.from_numpy(kpss.astype(np.float32)).to('cuda')
                # indices_gpu: (N,) - all point to frame 0
                indices_gpu = torch.zeros(len(faces), dtype=torch.long, device='cuda')
                
                chips_gpu = aligner.align_batched(frame_gpu, lms_gpu, indices_gpu)
                
                # Permute to NHWC and convert to uint8 (standard BGR chips)
                # We don't normalize yet because rec_model.get_feat() does its own normalization
                chips_gpu = chips_gpu.permute(0, 2, 3, 1)
                all_chips = list(chips_gpu.byte().cpu().numpy())
                
            # 3. Recognition
            embeddings = rec_model.get_feat(all_chips)
            
            # 4. Normalize and Clean Embeddings
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            embeddings = (embeddings / norms).astype(np.float32)
            embeddings = np.ascontiguousarray(embeddings)
            
            # Map embeddings back to face objects
            for i, face in enumerate(faces):
                face.embedding = embeddings[i]
                
            latency = (time.time() - start_time) * 1000
            
            # Update packet
            packet['faces'] = faces
            packet['emb_latency'] = latency
            packet['emb_timestamp'] = time.time()
            
            # Push to next stage (FAISS Search)
            cache.rpush("ryuk:embed", serde.pack(packet))
            
            if packet.get('frame_count', 0) % 50 == 0:
                print(f"PERF: Processed {packet['client_id']} | Faces: {len(faces)} | Latency: {latency:.2f}ms")
                
        except Exception as e:
            print(f"ERROR in Embedding Service: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)

if __name__ == "__main__":
    try:
        run_embedding_service()
    except KeyboardInterrupt:
        print("\nStopping Embedding Service...")
