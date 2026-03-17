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
    def __init__(self, client_id: str, source_url: Optional[str] = None):
        self.client_id = client_id
        self.source_url = source_url
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
        
        # Callbacks for detections (Multiple Listeners Support)
        self.listeners = set() # Set of objects with on_detection, on_stream_start, on_inactive
        
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

    def add_listener(self, listener):
        """Register a new UI listener for this processor."""
        with self._inf_lock:
            self.listeners.add(listener)

    def remove_listener(self, listener):
        """Unregister a UI listener."""
        with self._inf_lock:
            if listener in self.listeners:
                self.listeners.remove(listener)

    def _run(self):
        last_frame_time = 0.0
        is_active = False
        frame_key = f"stream:{self.client_id}:frame"
        
        # Pull model (RTSP) vs Push model (Redis)
        cap = None
        grabber_thread = None
        latest_frame_data = {"frame": None, "lock": threading.Lock(), "running": True}

        if self.source_url:
            print(f"DEBUG: Processor ({self.client_id}) - Opening RTSP stream: {self.source_url}")
            cap = cv2.VideoCapture(self.source_url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                print(f"DEBUG: Processor ({self.client_id}) - FAILED TO OPEN RTSP STREAM")
                return
            
            # RTSP Optimization: Set buffer size to 1 if supported
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            def grabber():
                while self.running and latest_frame_data["running"]:
                    ret, frame = cap.read()
                    if not ret:
                        print(f"DEBUG: Processor ({self.client_id}) - RTSP Read Failed. Retrying...")
                        break
                    with latest_frame_data["lock"]:
                        latest_frame_data["frame"] = frame
            
            grabber_thread = threading.Thread(target=grabber, daemon=True)
            grabber_thread.start()

        while self.running:
            frame = None
            
            if self.source_url:
                with latest_frame_data["lock"]:
                    frame = latest_frame_data["frame"]
                    latest_frame_data["frame"] = None # Consume the frame
                
                if frame is None:
                    time.sleep(0.005) # Small sleep to avoid CPU spinning
                    continue
            else:
                # Original Redis Pull
                raw = cache.get(frame_key)
                if raw:
                    frame = self._decode_frame(raw)
            
            if frame is not None:
                if not is_active:
                    is_active = True
                    with self._inf_lock:
                        for l in list(self.listeners):
                            if hasattr(l, 'on_stream_start'):
                                print(f"DEBUG: Processor ({self.client_id}) — Notifying listener on_stream_start")
                                l.on_stream_start(self.client_id)

                self._frame_count = (self._frame_count + 1) % 10_000
                
                # Trigger persistent worker (Non-blocking)
                if not self._is_inf_running and (self._frame_count % INFERENCE_THROTTLE == 0):
                    with self._inf_lock:
                        self._inf_frame = frame.copy()
                        self._inf_trigger.set()
                else:
                    with self._inf_lock:
                        self._tracker.predict()

                # Get latest track states for drawing (Skip stale ones for real-time responsiveness)
                faces_to_draw = []
                with self._inf_lock:
                    for tid, track in list(self._tracker._tracks.items()):
                        # Skip if stale even if not yet pruned by background thread
                        if track.is_stale:
                            continue
                            
                        meta = track.id_cache
                        if not meta:
                             _, _, meta = self._get_cached_identity(track)
                        
                        faces_to_draw.append({
                            "bbox": track.smoothed_bbox.astype(int),
                            "name": meta.get("name", "Unknown") if meta else "Unknown",
                            "threat": meta.get("threat_level", "Low") if meta else "Low"
                        })

                self._draw_frame(frame, faces_to_draw)
                encoded = self._encode_frame(frame)
                if encoded:
                    self.latest_processed_frame = encoded
                
                last_frame_time = time.time()
            else:
                # Inactivity logic: Works for both Redis and RTSP
                if is_active and (time.time() - last_frame_time > 5.0):
                    is_active = False
                    with self._inf_lock:
                        self._tracker.clear()
                        for l in list(self.listeners):
                            if hasattr(l, 'on_inactive'):
                                print(f"DEBUG: Processor ({self.client_id}) timed out after 5s of no frames.")
                                l.on_inactive(self.client_id)
                time.sleep(0.01) # Small sleep only when IDLE
        
        latest_frame_data["running"] = False
        if grabber_thread:
            grabber_thread.join(timeout=1.0)
        if cap:
            cap.release()

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
        
        # New: 180-degree rotation fallback for inverted faces
        if not raw_faces:
            # Rotate 180 degrees
            inf_frame_180 = cv2.rotate(inf_frame, cv2.ROTATE_180)
            raw_faces_180 = face_app.get(inf_frame_180)
            
            if raw_faces_180:
                # Map coordinates back to original orientation
                ih, iw = inf_frame.shape[:2]
                for face in raw_faces_180:
                    # Bbox: [x1, y1, x2, y2]
                    x1, y1, x2, y2 = face.bbox
                    # Inverted mapping: x' = w - x, y' = h - y
                    new_x1 = iw - x2
                    new_y1 = ih - y2
                    new_x2 = iw - x1
                    new_y2 = ih - y1
                    face.bbox = np.array([new_x1, new_y1, new_x2, new_y2])
                    
                    # Landmarks: [x, y]
                    if hasattr(face, 'landmark_2d_106') and face.landmark_2d_106 is not None:
                        face.landmark_2d_106[:, 0] = iw - face.landmark_2d_106[:, 0]
                        face.landmark_2d_106[:, 1] = ih - face.landmark_2d_106[:, 1]
                    if hasattr(face, 'landmark_3d_68') and face.landmark_3d_68 is not None:
                        face.landmark_3d_68[:, 0] = iw - face.landmark_3d_68[:, 0]
                        face.landmark_3d_68[:, 1] = ih - face.landmark_3d_68[:, 1]
                    
                    # Store rotation info if needed (optional)
                    face.rotated_180 = True
                
                raw_faces = raw_faces_180
        
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
            for l in list(self.listeners):
                if hasattr(l, 'on_detection'):
                    l.on_detection(res)
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
        h, w = frame.shape[:2]
        # Responsive thickness: on 4k (3840w), thinner than 2 would be invisible.
        base_thickness = max(1, int(w / 400))
        
        # Responsive font scaling: at 1600px width, font_scale is ~1.0
        font_scale = w / 1600.0
        font_scale = max(0.4, font_scale)
        text_thickness = max(1, int(base_thickness / 2))

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

            # Draw Bounding Box
            cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), main_color, base_thickness, cv2.LINE_4)
            
            label = f" {name.upper()} "
            font = cv2.FONT_HERSHEY_DUPLEX
            
            (tw, th), baseline = cv2.getTextSize(label, font, font_scale, text_thickness)
            
            # Position label: prefer above bbox, flip if off-screen top
            lx = bbox[0]
            ly = bbox[1] - base_thickness - 5
            
            if ly < th + 5:
                # If too high, flip inside the box at the top or just below box top
                ly = bbox[1] + th + base_thickness + 5
            
            # Ensure lx + tw doesn't exceed frame width
            if lx + tw > w:
                lx = w - tw
            lx = max(0, lx) # Floor to 0

            # Draw Label Background and Text
            cv2.rectangle(frame, (lx, ly - th - 3), (lx + tw, ly + 3), (10, 8, 5), -1)
            cv2.rectangle(frame, (lx, ly - th - 3), (lx + tw, ly + 3), main_color, 1, cv2.LINE_4)
            cv2.putText(frame, label, (lx, ly), font, font_scale, text_color, text_thickness, cv2.LINE_4)

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

            # frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            # frame = cv2.flip(frame, 1)
            return frame
        except Exception:
            return None
