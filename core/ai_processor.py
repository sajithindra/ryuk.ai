import warnings
import os
import numpy as np
import onnxruntime as ort
import ctypes
import threading
import queue
import time
import torch
import torch.nn.functional as F
from torchvision.transforms import v2 as transforms

# =============================================================================
# TENSORRT LIBRARY LOADING — Linking TRT 10 from venv
# =============================================================================
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_trt_lib_path = os.path.join(_project_root, ".venv", "lib", "python3.12", "site-packages", "tensorrt_libs")

if os.path.exists(_trt_lib_path):
    _curr_ld = os.environ.get("LD_LIBRARY_PATH", "")
    if _trt_lib_path not in _curr_ld:
        os.environ["LD_LIBRARY_PATH"] = f"{_trt_lib_path}:{_curr_ld}"
    
    try:
        ctypes.CDLL(os.path.join(_trt_lib_path, "libnvinfer.so.10"), mode=ctypes.RTLD_GLOBAL)
        ctypes.CDLL(os.path.join(_trt_lib_path, "libnvinfer_plugin.so.10"), mode=ctypes.RTLD_GLOBAL)
        ctypes.CDLL(os.path.join(_trt_lib_path, "libnvonnxparser.so.10"), mode=ctypes.RTLD_GLOBAL)
    except Exception:
        pass

warnings.filterwarnings("ignore", category=FutureWarning, module="insightface")
warnings.filterwarnings("ignore", category=FutureWarning, module="skimage")

from insightface.app import FaceAnalysis
from insightface.app.common import Face
from insightface.utils import face_align
from insightface.model_zoo import get_model
from config import (
    AI_BATCH_SIZE, AI_BATCH_TIMEOUT_MS, MAX_INFERENCE_SIZE
)

# =============================================================================
# IO BINDING WRAPPER
# =============================================================================
class IOBindingWrapper:
    def __init__(self, model_or_session):
        # Handle both insightface model objects (which have a .session)
        # and raw onnxruntime.InferenceSession objects.
        if hasattr(model_or_session, 'session'):
            self.model = model_or_session
            self.session = model_or_session.session
        else:
            self.model = None
            self.session = model_or_session
        self.io_binding = self.session.io_binding()
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        for name in self.output_names:
            self.io_binding.bind_output(name, 'cuda', 0)

    def run_optimized(self, blob):
        if torch.is_tensor(blob):
            # Direct GPU binding for Torch tensors
            # We need the data pointer and shape
            self.io_binding.bind_input(
                name=self.input_name,
                device_type='cuda',
                device_id=0,
                element_type=np.float32,
                shape=tuple(blob.shape),
                buffer_ptr=blob.data_ptr()
            )
        else:
            self.io_binding.bind_cpu_input(self.input_name, blob)
        
        self.session.run_with_iobinding(self.io_binding)
        return self.io_binding.copy_outputs_to_cpu()

# =============================================================================
# TORCH GPU TOOLS
# =============================================================================
class TorchFaceAligner:
    def __init__(self, device='cuda'):
        self.device = device
        # Standard 112x112 reference points for InsightFace
        self.reference_pts = torch.tensor([
            [30.2946, 51.6963],
            [65.5318, 51.5014],
            [48.0252, 71.7366],
            [33.5493, 92.3655],
            [62.7299, 92.2041]
        ], dtype=torch.float32, device=device)
        self.reference_pts = (self.reference_pts / 112.0) * 2.0 - 1.0 # Norm to [-1, 1]
        self.output_size = (112, 112)

    def align_batched(self, frames_gpu, landmarks_gpu, frame_indices):
        """
        frames_gpu: (B, 3, H, W) on GPU
        landmarks_gpu: (N, 5, 2) on GPU
        frame_indices: (N,) tensor of frame indices in frames_gpu
        """
        N = landmarks_gpu.shape[0]
        if N == 0: return torch.empty((0, 3, 112, 112), device=self.device)
        
        H, W = frames_gpu.shape[2:]
        
        # 1. Normalize landmarks to [-1, 1]
        lms_norm = landmarks_gpu.clone()
        lms_norm[..., 0] = (lms_norm[..., 0] / W) * 2.0 - 1.0
        lms_norm[..., 1] = (lms_norm[..., 1] / H) * 2.0 - 1.0
        
        # 2. Compute similarity matrices (N, 2, 3)
        ones = torch.ones(N, 5, 1, device=self.device)
        # Note: grid_sample expects destination to source mapping
        # So we solve for: reference_pts @ M = lms_norm
        # We solve: [ref, 1] @ X = lms_norm  => X is (3, 2)
        ref_aug = torch.cat([self.reference_pts.unsqueeze(0).expand(N, -1, -1), ones], dim=2)
        M_T = torch.linalg.lstsq(ref_aug, lms_norm).solution
        M = M_T.transpose(1, 2) # (N, 2, 3)
        
        # 3. Sample
        selected_frames = frames_gpu[frame_indices]
        grid = F.affine_grid(M, size=(N, 3, 112, 112), align_corners=False)
        chips = F.grid_sample(selected_frames, grid, align_corners=False, mode='bilinear', padding_mode='zeros')
        return chips


# =============================================================================
# GLOBAL AI PROCESSOR (SINGLETON)
# =============================================================================
class GlobalAIProcessor:
    def __init__(self, det_size=(640, 640), models_to_load=None, use_worker=True):
        """
        models_to_load: List of model names to load (e.g. ['detection', 'recognition']). 
                        If None, loads all default models.
        use_worker: If True, starts the internal batching worker thread.
        """
        self.det_size = det_size
        self._available = ort.get_available_providers()
        print(f"Initializing Global AI Processor | ORT {ort.__version__} | Providers: {self._available}")

        _TRT_CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "trt_cache")
        os.makedirs(_TRT_CACHE, exist_ok=True)

        _trt_options = {
            "device_id": 0,
            "trt_fp16_enable": True,
            "trt_engine_cache_enable": True,
            "trt_engine_cache_path": _TRT_CACHE,
            "trt_max_workspace_size": 4 * 1024 * 1024 * 1024, # 4 GB
            "trt_builder_optimization_level": 5,
            "trt_timing_cache_enable": True,
            "trt_timing_cache_path": _TRT_CACHE,
        }
        _cuda_options = {
            "device_id": 0,
            "gpu_mem_limit": 4 * 1024 * 1024 * 1024,
            "arena_extend_strategy": "kSameAsRequested",
        }

        providers = []
        if "TensorrtExecutionProvider" in self._available:
            providers.append(("TensorrtExecutionProvider", _trt_options))
        if "CUDAExecutionProvider" in self._available:
            providers.append(("CUDAExecutionProvider", _cuda_options))
        providers.append("CPUExecutionProvider")

        self.app = FaceAnalysis(name='buffalo_sc', providers=providers)
        self.app.prepare(ctx_id=0, det_size=det_size)



        # Post-Prepare: Prune unneeded models to save VRAM if specified
        if models_to_load is not None:
            for name in list(self.app.models.keys()):
                if name not in models_to_load:
                    print(f"  [PRUNING] Removing model: {name}")
                    del self.app.models[name]

        # IO Binding for detection models
        self._inf_lock = threading.Lock()
        
        if 'detection' in self.app.models:
            print("  [DEBUG] Setting up IO Binding for Face Detection")
            try:
                det_model = self.app.models['detection']
                self.det_wrapper = IOBindingWrapper(det_model)
                
                original_run = det_model.session.run
                def fast_run(output_names, input_feed, run_options=None):
                    if hasattr(self, 'det_wrapper') and self.det_wrapper.input_name in input_feed:
                        with self._inf_lock:
                            return self.det_wrapper.run_optimized(input_feed[self.det_wrapper.input_name])
                    return original_run(output_names, input_feed, run_options)
                det_model.session.run = fast_run
                print("  [IO BINDING ✓] Enabled for Face Detection")
            except Exception as e:
                print(f"  [IO BINDING ⚠] Face Detection Failed: {e}")



        # Batching Queue
        self.input_queue = queue.Queue(maxsize=32)
        self.aligner = TorchFaceAligner(device='cuda')
        
        if use_worker:
            self.worker_thread = threading.Thread(target=self._batch_worker, daemon=True)
            self.worker_thread.start()
        
        # Report status
        for name, model in self.app.models.items():
            active = model.session.get_providers()
            status = "[TRT ✓]" if "TensorrtExecutionProvider" in active else "[CUDA ✓]"
            print(f"  {status} {model.taskname} active")

    def get(self, frame):
        """Unified entry point for Processor. Returns Dict with faces."""
        res_event = threading.Event()
        result = {"faces": [], "event": res_event}
        self.input_queue.put((frame, result))
        
        # Wait for the batch worker to process it
        if not res_event.wait(timeout=2.0):
            return {"faces": []}
        return {"faces": result["faces"]}

    def _batch_worker(self):
        while True:
            # 1. Collect Batch
            batch = []
            try:
                # Wait for first item
                item = self.input_queue.get(timeout=1.0)
                batch.append(item)
                
                # Try to fill batch within AI_BATCH_TIMEOUT_MS
                deadline = time.time() + (AI_BATCH_TIMEOUT_MS / 1000.0)
                while len(batch) < AI_BATCH_SIZE:
                    remaining = deadline - time.time()
                    if remaining <= 0: break
                    try:
                        batch.append(self.input_queue.get(timeout=remaining))
                    except queue.Empty:
                        break
            except queue.Empty:
                continue

            # 2. Process Batch
            # Step A: Detection (Sequential as model is Batch-1)
            all_faces_per_frame = []
            
            for i, (frame, res_obj) in enumerate(batch):
                # Face Detection
                bboxes, kpss = self.app.models['detection'].detect(frame, max_num=0, metric='default')
                faces = []
                for j in range(bboxes.shape[0]):
                    face = Face(bbox=bboxes[j, 0:4], kps=kpss[j] if kpss is not None else None, det_score=bboxes[j, 4])
                    faces.append(face)
                all_faces_per_frame.append(faces)

            # Step B: Landmarks/Gender (Small batches or Sequential)
            # For simplicity, keep these sequential for now, they are very fast on TRT
            for i, (frame, _) in enumerate(batch):
                faces = all_faces_per_frame[i]
                for face in faces:
                    for taskname, model in self.app.models.items():
                        if taskname in ['detection', 'recognition']: continue
                        model.get(frame, face)

            # Step C: Recognition (GLOBAL BATCHED + GPU ACCELERATED)
            rec_model = self.app.models.get('recognition')
            if rec_model:
                landmarks = []
                chip_map = []
                
                for f_idx, (frame, _) in enumerate(batch):
                    for face in all_faces_per_frame[f_idx]:
                        landmarks.append(face.kps)
                        chip_map.append(f_idx)

                if landmarks:
                    # Move frames and landmarks to GPU for batched alignment
                    with torch.no_grad():
                        frames_gpu = torch.stack([
                            torch.from_numpy(f).to('cuda').permute(2, 0, 1).float() 
                            for f, _ in batch
                        ]) # (B, 3, H, W)
                        lms_gpu = torch.from_numpy(np.array(landmarks)).to('cuda').float() # (N, 5, 2)
                        indices_gpu = torch.tensor(chip_map, device='cuda')

                        # Batched Align on GPU
                        chips_gpu = self.aligner.align_batched(frames_gpu, lms_gpu, indices_gpu)
                        
                        # Permute to NHWC and convert to uint8 (standard BGR chips)
                        # We don't normalize yet because rec_model.get_feat() does its own normalization
                        chips_gpu = chips_gpu.permute(0, 2, 3, 1)
                        all_chips = list(chips_gpu.byte().cpu().numpy())

                    embeddings = rec_model.get_feat(all_chips)
                    
                    # Normalize, cast to float32, and ensure contiguous memory layout
                    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
                    norms = np.where(norms == 0, 1.0, norms)
                    embeddings = (embeddings / norms).astype(np.float32)
                    embeddings = np.ascontiguousarray(embeddings)

                    counts = [0] * len(batch)
                    for i, f_idx in enumerate(chip_map):
                        face_idx = counts[f_idx]
                        all_faces_per_frame[f_idx][face_idx].embedding = embeddings[i] # Already flat 1D in embeddings array
                        counts[f_idx] += 1

            # 3. Finalize and Signal
            for i, (_, res_obj) in enumerate(batch):
                res_obj["faces"] = all_faces_per_frame[i]
                res_obj["event"].set()

# Instantiate Singleton with DEFAULT behavior
face_app = GlobalAIProcessor(det_size=MAX_INFERENCE_SIZE if isinstance(MAX_INFERENCE_SIZE, tuple) else (MAX_INFERENCE_SIZE, MAX_INFERENCE_SIZE))

# Warmup
def warmup():
    print("GPU Warmup (Managed Batching)...")
    dummy = np.zeros((*face_app.det_size, 3), dtype=np.uint8)
    for _ in range(20):
        face_app.get(dummy)
    print("GPU Warmup Complete.")

threading.Thread(target=warmup, daemon=True).start()
