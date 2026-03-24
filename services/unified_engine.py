import os
import sys

# Add project root to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from core.bootstrap import bootstrap_gpu
bootstrap_gpu()

import time
import threading
import numpy as np

from core.ai_processor import face_app
from core.state import cache
import core.serialization as serde
import core.watchdog_indexer as watchdog
from core.ai.alpr.ocr import PlateOCR
from core.ai.alpr.tracker import PlateTracker
from core.ai.alpr.storage import ALPRStorage
from core.ai.alpr.cache import ALPRCache
from core.ai.alpr.utils import detect_color
from config import FAISS_THRESHOLD, AI_BATCH_SIZE, ALPR_CONFIG_PATH
import yaml

class UnifiedInferenceEngine:
    """
    Consolidated Inference Engine that handles detection, embedding, and 
    FAISS recognition in a high-performance batch-friendly pipeline.
    """
    def __init__(self):
        self.running = False
        self.log_file = open("/tmp/ryuk_engine.log", "a")
        self.log("[UnifiedEngine] Initialized and connected to GlobalAIProcessor.")
        self._decoders = {} # client_id -> JpegBatchDecoder
        self._decoder_lock = threading.Lock()
        
        # ALPR Components
        try:
            with open(ALPR_CONFIG_PATH, 'r') as f:
                self.alpr_config = yaml.safe_load(f)
            self.alpr_ocr = PlateOCR()
            self.alpr_storage = ALPRStorage(
                mongodb_uri=self.alpr_config['alpr']['storage']['mongodb_uri'],
                db_name=self.alpr_config['alpr']['storage']['db_name'],
                collection_name=self.alpr_config['alpr']['storage']['collection_name'],
                image_base_path=self.alpr_config['alpr']['storage']['image_base_path']
            )
            self.alpr_cache = ALPRCache(
                redis_url=self.alpr_config['alpr']['cache']['redis_url'],
                deduplication_ttl=self.alpr_config['alpr']['cache']['deduplication_ttl_sec']
            )
            self._alpr_trackers = {} # client_id -> PlateTracker
        except Exception as e:
            self.log(f"[UnifiedEngine] ALPR Init Error: {e}")
            self.alpr_config = None

    def _get_decoder(self, client_id, first_frame_raw):
        with self._decoder_lock:
            if client_id not in self._decoders:
                import cv2
                from core.hw_decoder import JpegBatchDecoder
                from config import USE_FFMPEG_CUDA
                
                if not USE_FFMPEG_CUDA:
                    return None
                
                # Decode once on CPU to get dimensions
                try:
                    arr = np.frombuffer(first_frame_raw, np.uint8)
                    temp = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if temp is not None:
                        h, w = temp.shape[:2]
                        self.log(f"[UnifiedEngine] Initializing HwDecoder for {client_id} ({w}x{h})")
                        self._decoders[client_id] = {
                            "decoder": JpegBatchDecoder(w, h),
                            "last_used": time.time()
                        }
                    else:
                        return None
                except:
                    return None
            
            entry = self._decoders[client_id]
            entry["last_used"] = time.time()
            return entry["decoder"]

    def log(self, msg):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] {msg}\n"
        self.log_file.write(formatted)
        self.log_file.flush()
        print(msg, flush=True)

    def process_frame(self, packet):
        """
        Processes a single frame packet.
        Returns the result packet for downstream consumption.
        """
        client_id = packet.get('client_id')
        frame = packet.get('frame')
        
        if frame is None and 'frame_bytes' in packet:
            # Decode frame if passed as bytes (from core/server.py)
            from config import USE_FFMPEG_CUDA
            if USE_FFMPEG_CUDA:
                decoder = self._get_decoder(client_id, packet['frame_bytes'])
                if decoder:
                    frame = decoder.decode(packet['frame_bytes'])
                
            if frame is None:
                # Fallback to CPU if decoder failed or disabled
                try:
                    import cv2
                    arr = np.frombuffer(packet['frame_bytes'], np.uint8)
                    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                except Exception as e:
                    print(f"[UnifiedEngine] Decode Error: {e}")
                    return None
                
        if frame is None: return None
        
        start_time = time.time()
        
        # 1. AI Inference (Batched internally by GlobalAIProcessor)
        res = face_app.get(frame)
        
        # Handle Inference Timeout or Error
        if res is None:
            self.log("[UnifiedEngine] WARNING: Inference returned None (timeout/error)")
            return None
            
        faces = res.get("faces", []) or []
        
        # 2. FAISS Search & Recognition
        search_results = []
        try:
            # Final safety check: ensure faces is a list and contains only valid items
            if faces is None: faces = []
            
            for face in faces:
                if face is None:
                    search_results.append({"name": "Unknown", "threat_level": "Low"})
                    continue
                    
                emb = getattr(face, 'embedding', None)
                if emb is None:
                    search_results.append({"name": "Unknown", "threat_level": "Low"})
                    continue
                    
                context = {
                    "pose": [float(p) for p in (getattr(face, "pose", [0,0,0]) or [0,0,0])],
                    "norm": 30.0
                }
                
                # Ensure we have a valid norm (either from insightface or GlobalAIProcessor)
                f_norm = getattr(face, 'norm', None)
                if f_norm is not None:
                    if hasattr(f_norm, 'item'):
                        f_norm = f_norm.item()
                    context["norm"] = float(f_norm)
                else:
                    # Fallback if norm is missing but det_score exists
                    det_s = getattr(face, "det_score", 0.9)
                    if hasattr(det_s, 'item'): det_s = det_s.item()
                    context["norm"] = float(det_s) * 30.0
                
                ident = watchdog.recognize_face(emb, threshold=FAISS_THRESHOLD, context=context)
                search_results.append(ident if ident else {"name": "Unknown", "threat_level": "Low"})
        except Exception as e:
            import traceback
            self.log(f"CRITICAL ERROR in Recognition Loop: {e}\n{traceback.format_exc()}")
            # Ensure search_results is populated even if loop fails partially
            while len(search_results) < len(faces):
                search_results.append({"name": "ERROR", "threat_level": "High"})
        
        latency = (time.time() - start_time) * 1000
        
            # 3. ALPR Tracking & OCR Logic
        plates = res.get("plates", []) or []
        alpr_results = []
        
        if self.alpr_config and plates:
            if client_id not in self._alpr_trackers:
                self._alpr_trackers[client_id] = PlateTracker(
                    max_age=self.alpr_config['alpr']['tracking']['max_age'],
                    iou_threshold=0.1 # Match tracker.py change
                )
            
            tracker = self._alpr_trackers[client_id]
            tracks = tracker.update(plates)
            
            for track in tracks:
                # Find matching detection robustly
                matching_det = None
                max_iou = 0.5
                for d in plates:
                    from core.deep_sort import iou
                    d_iou = iou(track.bbox, np.array(d['bbox']))
                    if d_iou > max_iou:
                        max_iou = d_iou
                        matching_det = d
                
                if not matching_det:
                    continue

                # Add to UI results
                alpr_results.append({
                    "bbox": track.bbox.tolist(),
                    "plate": track.plate_text,
                    "conf": track.ocr_confidence,
                    "label": f"{track.plate_text}" if track.plate_text else "License Plate"
                })
                
                # Perform Storage if newly validated
                if not track.ocr_completed and track.hits >= self.alpr_config['alpr']['tracking']['n_init']:
                    ocr_text = matching_det.get('ocr_text')
                    ocr_conf = matching_det.get('ocr_conf', 0.0)
                    
                    if ocr_text:
                        # Indian Plate Refinement
                        v_plate = self.alpr_ocr.validate_indian_plate(ocr_text)
                        
                        if v_plate:
                            # 4.1 High-Quality Plate Image Extraction
                            x1, y1, x2, y2 = map(int, track.bbox)
                            h_f, w_f = frame.shape[:2]
                            margin = 10 
                            x1_c, y1_c = int(max(0, x1 - margin)), int(max(0, y1 - margin))
                            x2_c, y2_c = int(min(w_f, x2 + margin)), int(min(h_f, y2 + margin))
                            
                            plate_crop = frame[y1_c:y2_c, x1_c:x2_c]
                            
                            if plate_crop.size > 0:
                                if not self.alpr_cache.is_duplicate(v_plate, client_id):
                                    img_p = self.alpr_storage.save_plate_image(plate_crop, v_plate, client_id)
                                    metadata = {
                                        "plate_number": v_plate,
                                        "camera_id": client_id,
                                        "timestamp": time.time(),
                                        "confidence": float(ocr_conf),
                                        "image_path": img_p,
                                        "bbox": track.bbox.tolist()
                                    }
                                    # Save and Publish
                                    from core.database import get_sync_db
                                    sync_db = get_sync_db()
                                    sync_db[self.alpr_config['alpr']['storage']['collection_name']].insert_one(metadata)
                                    self.alpr_cache.publish_event(metadata)
                                    
                                    track.plate_text = v_plate
                                    track.ocr_confidence = ocr_conf
                                    track.ocr_completed = True
                                    self.log(f"[ALPR] {client_id}: Detected {v_plate} (conf: {ocr_conf:.2f})")
            
            # Legacy UI update for this specific camera
            self.alpr_cache.push_ui_results(client_id, {"plates": alpr_results})

        # Construct the unified results packet
        result_packet = {
            "client_id": client_id,
            "frame_count": packet.get('frame_count', 0),
            "timestamp": packet.get('timestamp', time.time()),
            "faces": faces,  # Original detections for drawing
            "recognition": search_results, # Recognition results
            "plates": alpr_results,
            "latency": latency
        }
        
        return result_packet

    def start(self):
        """Starts the main ingestion loop."""
        self.running = True
        self.log("=" * 60)
        self.log("RYUK AI — UNIFIED INFERENCE ENGINE (GPU)")
        self.log("=" * 60)
        self.log("\n[READY] Waiting for ingestion stream ('ryuk:ingest')...")

        def worker():
            while self.running:
                try:
                    # RObust Frame Skipping: 
                    # If queue is too long, we are lagging. Pop and discard older frames.
                    q_len = cache.llen("ryuk:ingest")
                    if q_len > AI_BATCH_SIZE * 4:
                        # Batch discard: keep only the latest frames
                        # We pop 'q_len - AI_BATCH_SIZE' items to leave a small buffer for batching
                        to_discard = q_len - AI_BATCH_SIZE
                        for _ in range(to_discard):
                            cache.lpop("ryuk:ingest")
                        # self.log(f"[UnifiedEngine] Lag Detected! Discarded {to_discard} stale frames.")

                    packed = cache.blpop("ryuk:ingest", timeout=1)
                    if not packed: continue
                    
                    _, data = packed
                    packet = serde.unpack(data)
                    if not packet: continue
                    
                    # 2. Frame Stale Check (Timestamp based)
                    ts = packet.get('timestamp', 0)
                    if ts > 0 and (time.time() - ts) > 2.0: # 2s stale check for GPU inference
                        # self.log(f"[UnifiedEngine] Frame Stale ({time.time()-ts:.2f}s), skipping.")
                        continue

                    # Process the frame
                    result = self.process_frame(packet)
                    if result:
                        # Push to FAISS results queue for Sink Service
                        cache.rpush("ryuk:faiss", serde.pack(result))
                        
                        # Logging
                        if result['frame_count'] % 50 == 0:
                            n_plates = len(result.get('plates', []))
                            self.log(f"PERF: Processed {result['client_id']} | Faces: {len(result['faces'])} | Vehicles: {n_plates} | Latency: {result['latency']:.2f}ms")

                    # Periodically cleanup stale decoders (every 100 frames)
                    if packet.get('frame_count', 0) % 100 == 0:
                        self._cleanup_decoders()
                            
                except Exception as e:
                    self.log(f"ERROR in Unified Engine Worker: {e}")
                    time.sleep(0.1)

        # Use 2 workers — YOLO is not safely parallelized without TensorRT
        # _inf_lock in GlobalAIProcessor prevents race conditions
        threads = []
        for _ in range(2):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            threads.append(t)

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def _cleanup_decoders(self):
        """Terminates decoders that haven't been used for 60 seconds."""
        with self._decoder_lock:
            now = time.time()
            stale_keys = [k for k, v in self._decoders.items() if (now - v["last_used"]) > 60]
            for k in stale_keys:
                self.log(f"[UnifiedEngine] Cleaning up stale decoder for {k}")
                del self._decoders[k]

    def stop(self):
        self.running = False
        print("\nStopping Unified Engine...")

def run_unified_engine():
    engine = UnifiedInferenceEngine()
    engine.start()

if __name__ == "__main__":
    run_unified_engine()
