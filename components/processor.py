import time
import cv2
import numpy as np
import json
import threading
from typing import Callable, List, Dict, Optional

from core.state import cache, cache_str
from core.ai_processor import face_app
import core.watchdog_indexer as watchdog
from components.face_tracker import FaceTracker
from config import (
    INFERENCE_THROTTLE,
    MAX_INFERENCE_SIZE,
    FACE_CACHE_TTL_S,
    ALERT_COOLDOWN_S,
    LOG_COOLDOWN_S,
    FAISS_THRESHOLD,
    AUTO_AUGMENT_MIN_SIM,
    AUTO_AUGMENT_TILT_DEG,
)

class Processor:
    """
    Background Thread:
      1. Pulls JPEG frames from Redis as fast as possible.
      2. Decodes frames.
      3. Dispatches inference tasks to a background thread (non-blocking).
      4. Draws the LATEST available face results.
      5. Yields processed JPEG bytes.
    """
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.target_size = (640, 480)
        
        self._frame_count = 0
        self._last_faces: List[Dict] = []
        self._tracker = FaceTracker()
        
        self._is_inf_running = False
        self._inf_trigger = threading.Event()
        self._inf_lock = threading.Lock()
        self._inf_frame: Optional[np.ndarray] = None
        
        self.latest_processed_frame: Optional[bytes] = None
        
        # Callback for detections
        self.on_detection: Optional[Callable[[dict], None]] = None
        self.on_stream_start: Optional[Callable[[str], None]] = None
        self.on_inactive: Optional[Callable[[str], None]] = None
        
        # Start persistent worker (it will wait for .start() to set running=True)
        self._inf_worker_thread = threading.Thread(target=self._persistent_inf_worker, daemon=True)
        self._inf_worker_thread.start()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        # Thread will exit on its next loop iteration. No join needed.

    def _run(self):
        last_frame_time = 0.0
        is_active = False
        frame_key = f"stream:{self.client_id}:frame"

        while self.running:
            raw = cache.get(frame_key)

            if raw:
                if self._frame_count == 0:
                    print(f"DEBUG: Processor ({self.client_id}) successfully received first frame from Redis.")
                now = time.time()
                if now - last_frame_time < 0.033: # Target stable 30 FPS
                    continue

                frame = self._decode_frame(raw)
                if frame is None:
                    print(f"DEBUG: Processor ({self.client_id}) - FAILED TO DECODE FRAME ({len(raw)} bytes)")
                    continue

                last_frame_time = now
                if not is_active:
                    is_active = True
                    if self.on_stream_start:
                        self.on_stream_start(self.client_id)

                self._frame_count = (self._frame_count + 1) % 10_000
                
                # Trigger persistent worker (Non-blocking)
                if not self._is_inf_running and (self._frame_count % INFERENCE_THROTTLE == 0):
                    with self._inf_lock:
                        self._inf_frame = frame.copy()
                        self._inf_trigger.set()
                else:
                    with self._inf_lock:
                        self._tracker.predict()

                # Get latest track states (including predictions) for drawing
                faces_to_draw = []
                with self._inf_lock:
                    for tid, track in list(self._tracker._tracks.items()):
                        # Use local id_cache if available, otherwise fallback to redis
                        meta = track.id_cache
                        if not meta:
                             _, _, meta = self._get_cached_identity(track)
                        
                        faces_to_draw.append({
                            "bbox": track.smoothed_bbox.astype(int),
                            "name": meta.get("name", "Unknown") if meta else "Unknown",
                            "threat": meta.get("threat_level", "Low") if meta else "Low"
                        })

                self._draw_frame(frame, faces_to_draw)
                self.latest_processed_frame = self._encode_frame(frame)
                if self.latest_processed_frame is None:
                    print(f"DEBUG: Processor ({self.client_id}) - FAILED TO ENCODE FRAME")
                elif self._frame_count % 100 == 0:
                    print(f"DEBUG: Processor ({self.client_id}) - Streaming Active (Frame {self._frame_count})")

            else:
                if is_active and (time.time() - last_frame_time > 5.0):
                    is_active = False
                    with self._inf_lock:
                        self._tracker.clear()
                    if self.on_inactive:
                        print(f"DEBUG: Processor ({self.client_id}) timed out after 5s of no frames.")
                        self.on_inactive(self.client_id)
                time.sleep(0.01) # Small sleep only when IDLE

    def _persistent_inf_worker(self):
        """Persistent worker thread to avoid the overhead of spawning new threads."""
        while True: # Keep thread alive for entire app lifecycle
            self._inf_trigger.wait(timeout=1.0)
            if not self._inf_trigger.is_set() or not self.running:
                continue
                
            self._inf_trigger.clear()
            try:
                self._is_inf_running = True
                
                with self._inf_lock:
                    inf_frame = self._inf_frame
                    self._inf_frame = None
                    
                if inf_frame is not None:
                    try:
                        # Run AI in background
                        self._run_inference(inf_frame)
                    except Exception as e:
                        print(f"Processor ({self.client_id}): AI Worker Error — {e}")
            finally:
                self._is_inf_running = False

    def _run_inference(self, frame: np.ndarray) -> List[Dict]:
        h, w = frame.shape[:2]
        scale = min(MAX_INFERENCE_SIZE / w, MAX_INFERENCE_SIZE / h)
        inf_frame = (cv2.resize(frame,
                               (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA)
                     if scale < 1.0 else frame)
        if scale >= 1.0:
            scale = 1.0

        raw_faces = face_app.get(inf_frame)
        
        with self._inf_lock:
            tracked = self._tracker.update(raw_faces, scale)
            parsed_faces = []

            for item in tracked:
                track = item["track"]
                track_id = item["track_id"]
                raw_face = item["raw_face"]
                bbox = track.smoothed_bbox.astype(int)

                name, threat, meta = self._recognise(track, track_id)
                # CRITICAL: Store in track so main thread can see it immediately
                track.id_cache = meta

                if meta and hasattr(raw_face, "pose"):
                    aadhar = meta.get("aadhar")
                    self._try_auto_augment(aadhar, raw_face)

                aadhr = meta.get("aadhar") if meta else None
                if aadhr:
                    self._try_log(aadhr)
                if threat == "High":
                    self._try_alert(name)

                parsed_faces.append({
                    "bbox": bbox,
                    "name": name,
                    "threat": threat,
                })

            self._tracker.prune_stale()
        return parsed_faces

    def _get_cached_identity(self, track) -> tuple[str, str, dict | None]:
        """Helper to get name/threat from track cache or last AI results."""
        emb = track.avg_embedding
        emb_hash = hash(emb.tobytes()) & 0xFFFF_FFFF_FFFF_FFFF
        cache_key = f"cache:face:{emb_hash}"
        cached = cache_str.get(cache_key)
        if cached:
            meta = json.loads(cached)
            return meta.get("name", "Unknown"), meta.get("threat_level", "Low"), meta
        return "Unknown", "Low", None

    def _recognise(self, track, track_id: int) -> tuple[str, str, dict | None]:
        emb = track.avg_embedding
        emb_hash = hash(emb.tobytes()) & 0xFFFF_FFFF_FFFF_FFFF
        cache_key = f"cache:face:{emb_hash}"
        cached = cache_str.get(cache_key)

        if cached:
            meta = json.loads(cached)
            return meta.get("name", "Unknown"), meta.get("threat_level", "Low"), meta

        res = watchdog.recognize_face(emb, threshold=FAISS_THRESHOLD)
        if res and "aadhar" in res:
            if self.on_detection:
                self.on_detection(res)
            # Store in redis cache for other components
            cache_str.set(cache_key, json.dumps(res), ex=int(FACE_CACHE_TTL_S))
            return res.get("name", "Unknown"), res.get("threat_level", "Low"), res
        
        # If we got a score but it's below threshold, log it once for signal debugging
        if res and "score" in res and res["score"] > 0.1:
             print(f"BIO-LOG: Weak Signal — Max Score: {res['score']:.2f} (Threshold: {FAISS_THRESHOLD})")

        return "Unknown", "Low", None

    def _try_log(self, aadhar: str):
        lock_key = f"log_lock:{aadhar}:{self.client_id}"
        if not cache_str.get(lock_key):
            watchdog.log_activity(aadhar, self.client_id)
            cache_str.set(lock_key, "1", ex=int(LOG_COOLDOWN_S))

    def _try_alert(self, name: str):
        lock_key = f"alert_lock:{name}:{self.client_id}"
        if not cache_str.get(lock_key):
            msg = json.dumps({
                "type":      "SECURITY_ALERT",
                "message":   f"High Security Alert: {name} spotted at {self.client_id}",
                "name":      name,
                "source":    self.client_id,
                "timestamp": time.time(),
            })
            cache.publish("security_alerts", msg)
            cache_str.set(lock_key, "1", ex=int(ALERT_COOLDOWN_S))

    def _try_auto_augment(self, aadhar: str, face_obj):
        pose = face_obj.pose
        if any(abs(angle) > AUTO_AUGMENT_TILT_DEG for angle in pose):
            lock_key = f"aug_lock:{aadhar}"
            if not cache_str.get(lock_key):
                watchdog.augment_identity(aadhar, face_obj.embedding)
                cache_str.set(lock_key, "1", ex=3600)

    def _draw_frame(self, frame: np.ndarray, faces: List[Dict]):
        for pf in faces:
            bbox = pf["bbox"]
            name = pf["name"]
            threat = pf["threat"]
            
            if threat == "High":
                main_color = (83, 83, 255)    # Terracotta/Red
            elif threat == "Medium":
                main_color = (0, 140, 255)    # Tactical Orange
            else:
                main_color = (83, 222, 83)    # Safe Green
            text_color = (255, 255, 255)
            
            # Fast overlays: LINE_4 (cheaper than LINE_AA) and snap-to-face alpha (handled in tracker)
            cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), main_color, 1, cv2.LINE_4)
            
            label = f" {name.upper()} "
            font = cv2.FONT_HERSHEY_DUPLEX
            font_scale = 0.4
            thickness = 1
            (tw, th), _ = cv2.getTextSize(label, font, font_scale, thickness)
            
            lx, ly = bbox[0], bbox[1] - 8
            # Semi-transparent background for label would be nice, but solid is fastest
            cv2.rectangle(frame, (lx, ly - th - 3), (lx + tw, ly + 3), (10, 8, 5), -1)
            cv2.rectangle(frame, (lx, ly - th - 3), (lx + tw, ly + 3), main_color, 1, cv2.LINE_4)
            cv2.putText(frame, label, (lx, ly), font, font_scale, text_color, thickness, cv2.LINE_4)

    def _encode_frame(self, frame: np.ndarray) -> Optional[bytes]:
        try:
            # Quality 60 for speed, balance between bandwidth and speed
            res, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
            if not res:
                return None
            return buffer.tobytes()
        except Exception as e:
            print(f"Processor ({self.client_id}): Encode Error — {e}")
            return None

    def _decode_frame(self, raw: bytes) -> Optional[np.ndarray]:
        try:
            arr = np.frombuffer(raw, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None: return None
            
            # Optimization: If frame is huge (e.g. 4K), resize BEFORE expensive rotation
            h, w = frame.shape[:2]
            if w > 1280 or h > 1280:
                scale = 1280 / max(w, h)
                # Use NEAREST for 4K -> HD drop to save massive CPU time
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_NEAREST)

            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            frame = cv2.flip(frame, 1)
            return frame
        except Exception:
            return None
