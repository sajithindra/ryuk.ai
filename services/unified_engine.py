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
from core.deep_sort import DeepSortTracker
import json
from config import FAISS_THRESHOLD, AI_BATCH_SIZE, DETECTION_INTERVAL

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
        
        # 4. Sequential Trackers (One per Camera Stream)
        self._trackers: dict[str, DeepSortTracker] = {}
        self._tracker_locks: dict[str, threading.Lock] = {}
        self._global_tracker_lock = threading.Lock()

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
        frame_count = packet.get('frame_count', 0)
        
        # 1. Tracker Retrieval (Thread-Safe Per Stream)
        with self._global_tracker_lock:
            if client_id not in self._trackers:
                self._trackers[client_id] = DeepSortTracker()
                self._tracker_locks[client_id] = threading.Lock()
            tracker = self._trackers[client_id]
            lock = self._tracker_locks[client_id]

        faces = []
        objects = []
        search_results = []
        # 1. Determine if we need to search for faces (Biometric Quest)
        # We ONLY scan for faces if there is at least one unidentified person.
        person_tracks = [t for t in tracker.tracks.values() if t.label == 'person' and t.state == 1]
        needs_face_scan = any(not t.is_identified for t in person_tracks)
        
        # 2. Selective AI Inference (Detect Once, Track Persistent)
        # We define a "Grace Period" to stabilize velocity after identification.
        # This prevents the 'confusion' where detection drops abruptly after FR.
        stable_tracks = [t for t in person_tracks if t.is_identified and t.hits > (t.hits_at_id + 15 if hasattr(t, 'hits_at_id') else 15)]
        needs_stability = len(stable_tracks) < len(person_tracks)
        
        should_run_ai = (frame_count % DETECTION_INTERVAL == 0) or (len(person_tracks) == 0) or needs_face_scan or needs_stability

        with lock:
            if should_run_ai:
                res = face_app.get(frame, detect_faces=needs_face_scan, detect_objects=True)
                
                if res is not None:
                    faces_detected = res.get("faces", []) or []
                    objects_detected = res.get("objects", []) or []
                    
                    # Combine detections for tracker (YOLO objects + Faces if any)
                    tracker_input = objects_detected + faces_detected
                    tracker.update(tracker_input)
                    
                    # Store hits at point of identification for grace-period logic
                    # This tells the engine they've just been found, so stay in high-freq mode for a bit
                    for tid, track in tracker.tracks.items():
                        if track.is_identified and not hasattr(track, 'hits_at_id'):
                            track.hits_at_id = track.hits
                else:
                    tracker.predict()
            else:
                # High-efficiency path: Use motion models to advance tracks without running AI
                tracker.predict()
                faces_detected = [] # No new face detections this frame
            
            # 3. Association & Identity Pinning
            output_faces = []
            output_objects = [] # We'll return the person tracks mainly
            
            for tid, track in tracker.tracks.items():
                if track.state == 2: continue # Deleted
                
                # Include all tracked objects (person, car, etc.)
                bbox = track.smoothed_bbox.tolist()
                name = "Unknown"
                threat = "Low"
                
                if track.label == 'person':
                    # SEARCH FOR FACE INSIDE THIS PERSON BOX (if we ran detection)
                    if not track.is_identified and needs_face_scan:
                        for face in faces_detected:
                            f_bbox = face.bbox.tolist()
                            # Check if face box is mostly inside the person box
                            if (f_bbox[0] >= bbox[0]-10 and f_bbox[1] >= bbox[1]-10 and 
                                f_bbox[2] <= bbox[2]+10 and f_bbox[3] <= bbox[3]+10):
                                
                                # Found a face candidate for this person! Run Recognition.
                                if hasattr(face, 'embedding') and face.embedding is not None:
                                    context = {"pose": [0,0,0], "norm": 30.0}
                                    ident = watchdog.recognize_face(face.embedding, threshold=FAISS_THRESHOLD, context=context)
                                    if ident and ident.get("name") != "Unknown":
                                        track.identity = ident
                                        track.is_identified = True
                                        self.log(f"[IdentityQuest] Identified Track {tid} as '{ident['name']}'")
                                        break
                    
                    # Use Pinned Identity if available
                    if track.is_identified:
                        name = track.identity.get("name", "Unknown")
                        threat = track.identity.get("threat_level", "Low")
                else:
                    # Non-person objects (car, bottle, etc.)
                    name = track.label.capitalize()
                
                # Create the output object
                obj_dict = {
                    "track_id": tid,
                    "bbox": bbox,
                    "label": track.label,
                    "name": name,
                    "threat_level": threat,
                    "is_identified": track.is_identified
                }
                output_objects.append(obj_dict)
                
                if track.label == 'person':
                    # Also append to search_results for legacy compatibility if needed
                    search_results.append({"name": name, "threat_level": threat, "track_id": tid})
                
                elif track.label == 'face':
                    # If we are tracking legacy faces, add them too (optional)
                    if not any(obj['track_id'] == tid for obj in output_objects):
                        output_faces.append(track.raw_face if track.raw_face else {"bbox": bbox})

        latency = (time.time() - start_time) * 1000
        
        # 4. Construct the unified results packet
        result_packet = {
            "client_id": client_id,
            "frame_count": frame_count,
            "timestamp": packet.get('timestamp', time.time()),
            "faces": output_faces,  
            "objects": output_objects, # The primary person tracks with IDs
            "recognition": search_results, 
            "latency": latency,
            "biometric_active": needs_face_scan
        }
        
        return result_packet

    def start(self):
        """Starts the main ingestion loop."""
        self.running = True
        self.log("=" * 60)
        self.log("RYUK AI — UNIFIED INFERENCE ENGINE (GPU)")
        self.log("=" * 60)
        self.log("\n[READY] Waiting for ingestion stream ('ryuk:ingest')...")

        # Reinforcement Feedback Worker
        def feedback_worker():
            self.log("[UnifiedEngine] Feedback worker active.")
            while self.running:
                try:
                    packed = cache.blpop("ryuk:feedback", timeout=1.0)
                    if packed:
                        _, data = packed
                        feedback = json.loads(data)
                        det_id = feedback.get('det_id')
                        is_correct = feedback.get('is_correct')
                        if det_id is not None and is_correct is not None:
                            face_app.save_feedback(det_id, is_correct)
                except Exception as e:
                    self.log(f"Feedback worker error: {e}")
                    time.sleep(1.0)
        
        fb_thread = threading.Thread(target=feedback_worker, daemon=True)
        fb_thread.start()

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
                            self.log(f"PERF: Processed {result['client_id']} | Faces: {len(result['faces'])} | Latency: {result['latency']:.2f}ms")

                    # Periodically cleanup stale decoders (every 100 frames)
                    if packet.get('frame_count', 0) % 100 == 0:
                        self._cleanup_decoders()
                            
                except Exception as e:
                    self.log(f"ERROR in Unified Engine Worker: {e}")
                    time.sleep(0.1)

        # Start multiple workers to saturate the batching logic in face_app
        threads = []
        for _ in range(AI_BATCH_SIZE * 2):
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
