"""
core/ai/engine.py
Modular Global AI Processor and Batching Engine.
"""
import os
import threading
import queue
import time
import uuid
import cv2
import numpy as np
import torch
import onnxruntime as ort
from insightface.app import FaceAnalysis
from insightface.app.common import Face
from ultralytics import YOLO
from core.logger import logger
from core.ai.utils import IOBindingWrapper, TorchFaceAligner, TorchPreprocessor
from config import AI_BATCH_SIZE, AI_BATCH_TIMEOUT_MS, DATA_DIR, ENABLE_TENSORRT, ENABLE_CUDA

class GlobalAIProcessor:
    def __init__(self, det_size=(640, 640), use_worker=True):
        self.det_size = det_size
        self._available = ort.get_available_providers()
        _TRT_CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "trt_cache")
        os.makedirs(_TRT_CACHE, exist_ok=True)

        providers = self._get_providers(_TRT_CACHE)
        self.app = FaceAnalysis(name='buffalo_sc', providers=providers, allowed_modules=['detection', 'recognition'])
        self.app.prepare(ctx_id=0, det_size=det_size)

        self.gpu_lock = threading.Lock() # Single lock to prevent CUDA stream collisions
        self._setup_io_binding()

        self.input_queue = queue.Queue(maxsize=32)
        self.aligner = TorchFaceAligner(device='cuda')
        self.preprocessor = TorchPreprocessor(target_size=self.det_size, device='cuda')
        
        # Reinforcement Training Buffer
        self.training_cache = {} # {id: (frame, label, bbox)}
        self.training_dir = os.path.join(DATA_DIR, "training_data")
        os.makedirs(os.path.join(self.training_dir, "positive"), exist_ok=True)
        os.makedirs(os.path.join(self.training_dir, "negative"), exist_ok=True)
        
        # Load YOLO for general object detection
        try:
            self.yolo = YOLO('yolo11n.pt')
            # To ensure it's on CUDA if available
            if torch.cuda.is_available():
                self.yolo.to('cuda')
            logger.info("[YOLO] Enabled for Object Detection (yolo11n)")
        except Exception as e:
            logger.error(f"[YOLO] Initialization failed: {e}")
            self.yolo = None
            
        # Load YOLO Pose for Activity Recognition
        try:
            self.yolo_pose = YOLO('yolo11n-pose.pt')
            if torch.cuda.is_available():
                self.yolo_pose.to('cuda')
            logger.info("[YOLO-Pose] Enabled for Activity Detection (yolo11n-pose)")
        except Exception as e:
            logger.error(f"[YOLO-Pose] Initialization failed: {e}")
            self.yolo_pose = None
        
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
        if ENABLE_TENSORRT and "TensorrtExecutionProvider" in self._available: 
            providers.append(("TensorrtExecutionProvider", _trt_options))
        if ENABLE_CUDA and "CUDAExecutionProvider" in self._available: 
            providers.append(("CUDAExecutionProvider", _cuda_options))
        
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
                        with self.gpu_lock:
                            return self.det_wrapper.run_optimized(input_feed[self.det_wrapper.input_name])
                    return original_run(output_names, input_feed, run_options)
                # det_model.session.run = fast_run
                logger.info("[IO BINDING] Enabled for Face Detection")
            except Exception as e:
                logger.error(f"[IO BINDING] Failed: {e}")

    def get(self, frame, priority=False, detect_faces=True, detect_objects=True):
        res_event = threading.Event()
        result = {"faces": [], "objects": [], "event": res_event}
        flags = {"detect_faces": detect_faces, "detect_objects": detect_objects}
        
        try:
            # 1. Backlog handling: Drop live frames if queue is full, but ALWAYS process priority (Enrollment) frames.
            if not priority and self.input_queue.qsize() > 5:
                return {"faces": [], "objects": []}
            
            # 2. Add to queue: Priority frames get a much longer wait to enter the queue
            put_timeout = 5.0 if priority else 0.5
            self.input_queue.put((frame, result, flags), timeout=put_timeout)
        except queue.Full:
            return {"faces": [], "objects": []}
            
        # 3. Wait for Results: Priority (Enrollment) expects a longer processing window (10s)
        wait_timeout = 10.0 if priority else 3.0
        if not res_event.wait(timeout=wait_timeout):
            logger.warning(f"AI: Request timeout (priority={priority})")
            return {"faces": [], "objects": []}
        return {"faces": result.get("faces", []), "objects": result.get("objects", [])}

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
                for _, res, _ in batch:
                     if isinstance(res, dict) and "event" in res:
                         res["event"].set()

    def _process_batch(self, batch):
        valid_indices = [i for i, item in enumerate(batch) if item[0] is not None]
        valid_frames = [batch[i][0] for i in valid_indices]
        
        if not valid_frames:
            for _, res, _ in batch:
                res["faces"] = []
                res["objects"] = []
                res["event"].set()
            return

        det_model = self.app.models.get('detection')
        all_faces = [] 
        all_objects = []

        # SYNCHRONIZED GPU EXECUTION to prevent legacy stream dependency errors
        with self.gpu_lock:
            # 1. Face Detection (Selective)
            for i, (f_idx) in enumerate(valid_indices):
                frame = valid_frames[i]
                flags = batch[f_idx][2]
                
                if flags.get("detect_faces", True):
                    det_res = det_model.detect(frame, max_num=100)
                    bboxes, kpss = det_res[0], det_res[1]
                    faces = [Face(bbox=bboxes[j, 0:4], kps=kpss[j], det_score=bboxes[j, 4]) 
                            for j in range(len(bboxes))] if bboxes is not None else []
                    all_faces.append(faces)
                else:
                    all_faces.append([])

            # 2. YOLO Object Detection (Selective)
            if self.yolo:
                # Group frames that actually need YOLO
                yolo_indices = [i for i, idx in enumerate(valid_indices) if batch[idx][2].get("detect_objects", True)]
                yolo_frames = [valid_frames[i] for i in yolo_indices]
                all_objects = [[] for _ in range(len(valid_frames))]
                
                if yolo_frames:
                    # logger.debug(f"[YOLO] Processing batch of {len(yolo_frames)} frames")
                    # Optimized: 0.45 threshold eliminates majority of false positives
                    yolo_results = self.yolo(yolo_frames, stream=True, verbose=False, conf=0.45, iou=0.5)
                    for i, r in enumerate(yolo_results):
                        orig_idx = yolo_indices[i] 
                        frame_objs = []
                        boxes = r.boxes
                        if len(boxes) > 0:
                            # Use orig_idx to map back to the correct frame in the batch
                            logger.info(f"[YOLO] Batch Match: Detected {len(boxes)} objects in frame index {orig_idx}")
                        
                        for box in boxes:
                            det_id = str(uuid.uuid4())[:8]
                            label = self.yolo.names[int(box.cls[0])]
                            conf_val = float(box.conf[0])
                            
                            # HIGH-INTEREST ONLY (Filter out static objects like chairs, plants)
                            high_interest = ["person", "car", "motorcycle", "bicycle", "bus", "truck", "dog", "cat", "handgun"]
                            if label.lower() not in high_interest:
                                continue
                                
                            # Class-specific confidence filtering (combat "ghost" person detections)
                            if label.lower() == "person" and conf_val < 0.60:
                                continue
                                
                            bbox = box.xyxy[0].tolist()
                            
                            # Cache for reinforcement training
                            if len(self.training_cache) > 5000:
                                self.training_cache.pop(next(iter(self.training_cache)))
                            self.training_cache[det_id] = (valid_frames[orig_idx].copy(), label, bbox)

                            # Check keypoints if pose model is active
                            action = "Unknown"
                            
                            frame_objs.append({
                                "det_id": det_id,
                                "bbox": bbox,
                                "label": label,
                                "confidence": conf_val,
                                "action": action
                            })
                        all_objects[orig_idx] = frame_objs
                
                # Run YOLO Pose only on frames that had a person detected
                if self.yolo_pose and yolo_frames:
                    # Collect frames where at least one person was found
                    pose_indices = []
                    pose_frames = []
                    for i, orig_idx in enumerate(yolo_indices):
                        has_person = any(obj['label'] == 'person' for obj in all_objects[orig_idx])
                        if has_person:
                            pose_indices.append(orig_idx)
                            pose_frames.append(yolo_frames[i])
                    
                    if pose_frames:
                        pose_results = self.yolo_pose(pose_frames, stream=True, verbose=False, conf=0.45)
                        for i, p_r in enumerate(pose_results):
                            orig_idx = pose_indices[i]
                            if not p_r.keypoints or p_r.keypoints.data.shape[1] == 0:
                                continue
                            
                            # Match pose bounding boxes with person bounding boxes
                            for p_idx, p_box in enumerate(p_r.boxes.xyxy):
                                p_bbox = p_box.tolist()
                                p_kpts = p_r.keypoints.data[p_idx] # shape (17, 3)
                                
                                # Find best matching person box in all_objects[orig_idx]
                                best_iou = 0
                                best_obj = None
                                
                                for obj in all_objects[orig_idx]:
                                    if obj['label'] != 'person': continue
                                    o_bbox = obj['bbox']
                                    # Calculate IoU
                                    xA = max(p_bbox[0], o_bbox[0])
                                    yA = max(p_bbox[1], o_bbox[1])
                                    xB = min(p_bbox[2], o_bbox[2])
                                    yB = min(p_bbox[3], o_bbox[3])
                                    interArea = max(0, xB - xA) * max(0, yB - yA)
                                    boxAArea = (p_bbox[2] - p_bbox[0]) * (p_bbox[3] - p_bbox[1])
                                    boxBArea = (o_bbox[2] - o_bbox[0]) * (o_bbox[3] - o_bbox[1])
                                    iou = interArea / float(boxAArea + boxBArea - interArea)
                                    
                                    if iou > best_iou:
                                        best_iou = iou
                                        best_obj = obj
                                        
                                if best_iou > 0.5 and best_obj is not None:
                                    # Classify pose
                                    # Keypoints: 11, 12 = hips | 13, 14 = knees | 15, 16 = ankles
                                    # Simple heuristic for Sitting vs Standing
                                    # If the hips are placed vertically close to the knees, they're sitting.
                                    try:
                                        hip_y = (p_kpts[11][1] + p_kpts[12][1]) / 2.0
                                        knee_y = (p_kpts[13][1] + p_kpts[14][1]) / 2.0
                                        ankle_y = (p_kpts[15][1] + p_kpts[16][1]) / 2.0
                                        
                                        hip_to_knee = knee_y - hip_y
                                        knee_to_ankle = ankle_y - knee_y
                                        
                                        # Hips confidence > 0.5 and Knees confidence > 0.5
                                        if min(p_kpts[11][2], p_kpts[12][2], p_kpts[13][2], p_kpts[14][2]) > 0.4:
                                            # If hip-to-knee vertical distance is very small compared to knee-to-ankle, likely sitting
                                            if hip_to_knee < knee_to_ankle * 0.5:
                                                best_obj['action'] = "Sitting"
                                            else:
                                                best_obj['action'] = "Standing"
                                    except Exception:
                                        pass
            else:
                all_objects = [[] for _ in valid_frames]

            # 3. Attributes & Recognition (only for valid frames with faces)
            rec_model = self.app.models.get('recognition')
            if rec_model and any(all_faces): # Only proceed if there are any faces detected across the batch
                all_chips = []
                chip_map = [] 
                
                for i, frame in enumerate(valid_frames):
                    faces = all_faces[i]
                    if not faces: continue
                    
                    frame_gpu = torch.from_numpy(np.ascontiguousarray(frame).copy()).to('cuda', non_blocking=True).permute(2, 0, 1).float().unsqueeze(0)
                    lms_gpu = torch.from_numpy(np.array([f.kps for f in faces]).copy()).to('cuda', non_blocking=True).float()
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
                        n_val = norms[i, 0]
                        if hasattr(n_val, 'item'): n_val = n_val.item()
                        all_faces[f_idx][face_idx].norm = float(n_val)

        # 4. Map results back to original batch items
        valid_frame_ptr = 0
        for i, (frame, res, flags) in enumerate(batch):
            if i in valid_indices:
                res["faces"] = all_faces[valid_frame_ptr]
                res["objects"] = all_objects[valid_frame_ptr]
                valid_frame_ptr += 1
            else:
                res["faces"] = []
                res["objects"] = []
            res["event"].set()

    def save_feedback(self, det_id, is_correct):
        """Save a sample for reinforcement training based on user feedback."""
        if det_id not in self.training_cache:
            logger.warning(f"Feedback received for expired det_id: {det_id}")
            return False
            
        frame, label, bbox = self.training_cache.pop(det_id)
        folder = "positive" if is_correct else "negative"
        save_path = os.path.join(self.training_dir, folder)
        
        # Ensure directories exist (safeguard)
        os.makedirs(save_path, exist_ok=True)
        
        timestamp = int(time.time())
        filename = f"{label}_{det_id}_{timestamp}.jpg"
        full_path = os.path.join(save_path, filename)
        
        try:
            # We save the full frame for better training context
            cv2.imwrite(full_path, frame)
            # Future: Save YOLO format label.txt here too
            logger.info(f"Reinforcement Data Saved: {full_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save feedback data: {e}")
            return False
