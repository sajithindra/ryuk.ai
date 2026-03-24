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
from config import FAISS_THRESHOLD, AI_BATCH_SIZE

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
        
        # Construct the unified results packet
        result_packet = {
            "client_id": client_id,
            "frame_count": packet.get('frame_count', 0),
            "timestamp": packet.get('timestamp', time.time()),
            "faces": faces,  # Original detections for drawing
            "recognition": search_results, # Recognition results
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
