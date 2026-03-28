"""
core/ai/engine.py
Modular Global AI Processor and Batching Engine.
"""
import os
import threading
import queue
import time
import numpy as np
import torch
import onnxruntime as ort
from insightface.app import FaceAnalysis
from insightface.app.common import Face
from core.logger import logger
from core.ai.utils import IOBindingWrapper, TorchFaceAligner, TorchPreprocessor
from config import AI_BATCH_SIZE, AI_BATCH_TIMEOUT_MS

class GlobalAIProcessor:
    def __init__(self, det_size=(640, 640), use_worker=True):
        self.det_size = det_size
        self._available = ort.get_available_providers()
        _TRT_CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "trt_cache")
        os.makedirs(_TRT_CACHE, exist_ok=True)

        providers = self._get_providers(_TRT_CACHE)
        self.app = FaceAnalysis(name='buffalo_sc', providers=providers, allowed_modules=['detection', 'recognition'])
        self.app.prepare(ctx_id=0, det_size=det_size)

        self._inf_lock = threading.Lock()
        self._setup_io_binding()

        self.input_queue = queue.Queue(maxsize=32)
        self.aligner = TorchFaceAligner(device='cuda')
        self.preprocessor = TorchPreprocessor(target_size=self.det_size, device='cuda')
        
        if use_worker:
            # Multi-threaded batch workers for higher throughput
            # Since ORT/TRT is thread-safe for run(), we can parallelize detection
            for i in range(4): # 4 parallel batch workers
                t = threading.Thread(target=self._batch_worker, name=f"AIWorker-{i}", daemon=True)
                t.start()

    def _get_providers(self, cache_path):
        _trt_options = {
            "device_id": 0, "trt_fp16_enable": True, "trt_engine_cache_enable": True,
            "trt_engine_cache_path": cache_path, "trt_max_workspace_size": 1 * 1024 * 1024 * 1024,
            "trt_builder_optimization_level": 5, "trt_timing_cache_enable": True,
            "trt_timing_cache_path": cache_path,
        }
        _cuda_options = {"device_id": 0, "gpu_mem_limit": 1 * 1024 * 1024 * 1024, "arena_extend_strategy": "kSameAsRequested"}
        
        providers = []
        if "TensorrtExecutionProvider" in self._available: providers.append(("TensorrtExecutionProvider", _trt_options))
        if "CUDAExecutionProvider" in self._available: providers.append(("CUDAExecutionProvider", _cuda_options))
        providers.append("CPUExecutionProvider")
        return providers

    def _setup_io_binding(self):
        if 'detection' in self.app.models:
            try:
                det_model = self.app.models['detection']
                self.det_wrapper = IOBindingWrapper(det_model)
                original_run = det_model.session.run
                def fast_run(output_names, input_feed, run_options=None):
                    if self.det_wrapper.input_name in input_feed:
                        with self._inf_lock:
                            return self.det_wrapper.run_optimized(input_feed[self.det_wrapper.input_name])
                    return original_run(output_names, input_feed, run_options)
                # det_model.session.run = fast_run
                logger.info("[IO BINDING] Enabled for Face Detection")
            except Exception as e:
                logger.error(f"[IO BINDING] Failed: {e}")

    def get(self, frame):
        res_event = threading.Event()
        result = {"faces": [], "event": res_event}
        try:
            # Aggressive frame dropping if backlog exists
            if self.input_queue.qsize() > 5:
                return {"faces": []}
            self.input_queue.put((frame, result), timeout=0.5) # Reduced timeout
        except queue.Full:
            return {"faces": []}
            
        if not res_event.wait(timeout=3.0):
            return {"faces": []}
        return {"faces": result["faces"]}

    def _batch_worker(self):
        while True:
            batch = []
            try:
                item = self.input_queue.get(timeout=1.0)
                batch.append(item)
                deadline = time.time() + (AI_BATCH_TIMEOUT_MS / 1000.0)
                while len(batch) < AI_BATCH_SIZE:
                    remaining = deadline - time.time()
                    if remaining <= 0: break
                    try: batch.append(self.input_queue.get(timeout=remaining))
                    except queue.Empty: break
                
                self._process_batch(batch)
            except queue.Empty: continue
            except Exception as e:
                logger.error(f"Batch worker error: {e}")
                for _, res in batch: res["event"].set()

    def _process_batch(self, batch):
        # 1. Detection
        # Separate frames and keep track of original indices for mapping results
        valid_indices = [i for i, (frame, _) in enumerate(batch) if frame is not None]
        valid_frames = [batch[i][0] for i in valid_indices]
        
        if not valid_frames:
            for _, res in batch:
                res["faces"] = []
                res["event"].set()
            return

        det_model = self.app.models.get('detection')
        all_faces = [] # Parallel to valid_frames
        
        for frame in valid_frames:
            # Use det_model directly for finer control, max_num=100 to ensure we don't accidentally limit to 0
            bboxes, kpss = det_model.detect(frame, max_num=100)
            faces = [Face(bbox=bboxes[j, 0:4], kps=kpss[j], det_score=bboxes[j, 4]) 
                    for j in range(len(bboxes))] if bboxes is not None else []
            all_faces.append(faces)

        # 2. Attributes & Recognition (only for valid frames with faces)
        rec_model = self.app.models.get('recognition')
        if rec_model and any(all_faces):
            all_chips = []
            chip_map = [] # list of (all_faces_idx, face_idx)
            
            with torch.no_grad():
                for i, frame in enumerate(valid_frames):
                    faces = all_faces[i]
                    if not faces: continue
                    
                    # Batched alignment for this frame's faces
                    frame_gpu = torch.from_numpy(np.ascontiguousarray(frame).copy()).to('cuda', non_blocking=True).permute(2, 0, 1).float().unsqueeze(0)
                    lms_gpu = torch.from_numpy(np.array([f.kps for f in faces])).to('cuda', non_blocking=True).float()
                    chips = self.aligner.align_batched(frame_gpu, lms_gpu, torch.zeros(len(faces), dtype=torch.long, device='cuda'))
                    chips_np = chips.permute(0, 2, 3, 1).byte().cpu().numpy()
                    
                    for j, chip in enumerate(chips_np):
                        all_chips.append(chip)
                        chip_map.append((i, j))
            
            if all_chips:
                feats = rec_model.get_feat(all_chips)
                norms = np.linalg.norm(feats, axis=1, keepdims=True)
                norms = np.where(norms == 0, 1.0, norms)
                feats = (feats / norms).astype(np.float32)
                
                for i, (f_idx, face_idx) in enumerate(chip_map):
                    all_faces[f_idx][face_idx].embedding = feats[i]
                    # Ensure scalar conversion is safe
                    n_val = norms[i, 0]
                    if hasattr(n_val, 'item'):
                        n_val = n_val.item()
                    all_faces[f_idx][face_idx].norm = float(n_val)

        # 3. Map results back to original batch items
        valid_frame_ptr = 0
        for i, (frame, res) in enumerate(batch):
            if i in valid_indices:
                res["faces"] = all_faces[valid_frame_ptr]
                valid_frame_ptr += 1
            else:
                res["faces"] = []
            res["event"].set()
