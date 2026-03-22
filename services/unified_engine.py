import os
import sys
import time
import threading
import numpy as np

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
                    "pose": getattr(face, "pose", [0, 0, 0]) or [0, 0, 0],
                    "norm": float(np.linalg.norm(emb))
                }
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
                    packed = cache.blpop("ryuk:ingest", timeout=1)
                    if not packed: continue
                    
                    _, data = packed
                    packet = serde.unpack(data)
                    if not packet: continue
                    
                    # Process the frame
                    result = self.process_frame(packet)
                    if result:
                        # Push to FAISS results queue for Sink Service
                        cache.rpush("ryuk:faiss", serde.pack(result))
                        
                        # Logging
                        if result['frame_count'] % 50 == 0:
                            self.log(f"PERF: Processed {result['client_id']} | Faces: {len(result['faces'])} | Latency: {result['latency']:.2f}ms")
                            
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

    def stop(self):
        self.running = False
        print("\nStopping Unified Engine...")

def run_unified_engine():
    engine = UnifiedInferenceEngine()
    engine.start()

if __name__ == "__main__":
    run_unified_engine()
