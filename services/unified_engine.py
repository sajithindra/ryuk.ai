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
from config import FAISS_THRESHOLD, AI_BATCH_SIZE, DETECTION_INTERVAL, TRACKING_ONLY_ENABLED

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
        
        # Per-client tracking state
        self.trackers = {} # client_id -> DeepSortTracker
        self.frame_counts = {} # client_id -> int (frames since last detect)
        self._tracker_lock = threading.Lock()

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
        
        # 1. State Management
        with self._tracker_lock:
            if client_id not in self.trackers:
                self.trackers[client_id] = DeepSortTracker()
                self.frame_counts[client_id] = 0
            
            tracker = self.trackers[client_id]
            self.frame_counts[client_id] += 1
            
            # Decide: run detection or only track?
            run_detection = False
            if not TRACKING_ONLY_ENABLED:
                run_detection = True
            elif self.frame_counts[client_id] >= DETECTION_INTERVAL:
                run_detection = True
            elif not tracker.tracks:
                run_detection = True
        
        faces = []
        search_results = []
        
        if run_detection:
            # Full Detection & Recognition Path
            res = face_app.get(frame)
            if res:
                detected_faces = res.get("faces", []) or []
                tracker.predict() # Always predict before update
                tracker.update(detected_faces)
                self.frame_counts[client_id] = 0
                # self.log(f"[UnifiedEngine] Full Detection for {client_id}")
            else:
                self.log("[UnifiedEngine] WARNING: Inference returned None")
        else:
            # Efficient Tracking-Only Path
            tracker.predict()
            # Age tracks even if not updating with detections
            tracker.update([]) 
            # self.log(f"[UnifiedEngine] Tracking Only for {client_id}")
            
        # 2. Extract Results from Tracker (Common for both paths)
        active_tracks = [t for t in tracker.tracks.values() if t.state == 1 or t.hits > 0]
        
        for track in active_tracks:
            # Convert track back to a format downstream expects
            # We use a dummy Face-like dict for compatibility
            face_data = {
                "bbox": track.smoothed_bbox,
                "track_id": track.track_id,
                "det_score": 1.0 if not run_detection else 0.9, # Tracker confidence
                "embedding": track.face_embedding
            }
            faces.append(face_data)
            
            # Identification Persistence (Dynamic Lookup)
            if track.identity_id:
                # Fetch latest metadata from WatchdogIndexer
                latest_meta = watchdog.get_metadata(track.identity_id)
                if latest_meta:
                    search_results.append(latest_meta)
                else:
                    # Profile might have been deleted, fallback
                    search_results.append({"name": "Unknown", "threat_level": "Low"})
            elif track.face_embedding is not None:
                # Need to recognize
                try:
                    context = {"pose": [0,0,0], "norm": 30.0}
                    ident = watchdog.recognize_face(track.face_embedding, threshold=FAISS_THRESHOLD, context=context)
                    if ident and ident.get("aadhar") and ident.get("aadhar") != "Unknown":
                        track.identity_id = ident["aadhar"] # Pin the ID, not the whole dict
                    search_results.append(ident if ident else {"name": "Unknown", "threat_level": "Low"})
                except:
                    search_results.append({"name": "Unknown", "threat_level": "Low"})
            else:
                search_results.append({"name": "Unknown", "threat_level": "Low"})
        
        latency = (time.time() - start_time) * 1000
        
        # Construct the unified results packet
        result_packet = {
            "client_id": client_id,
            "frame_count": packet.get('frame_count', 0),
            "timestamp": packet.get('timestamp', time.time()),
            "faces": faces,
            "recognition": search_results,
            "latency": latency,
            "is_tracked": not run_detection
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
