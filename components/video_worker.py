import time
import cv2
import numpy as np
import json
import threading

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui  import QImage

from core.state    import cache, cache_str
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


class VideoProcessor(QThread):
    """
    Background QThread:
      1. Pulls JPEG frames from Redis as fast as possible.
      2. Decodes frames.
      3. Dispatches inference tasks to a background thread (non-blocking).
      4. Draws the LATEST available face results.
      5. Emits to UI.
    """
    frame_ready      = pyqtSignal(QImage)
    stream_inactive  = pyqtSignal(str)   # emits client_id
    person_identified = pyqtSignal(dict)  # emits identity metadata

    def __init__(self, client_id: str):
        super().__init__()
        self.client_id       = client_id
        self.running         = True
        self.target_size     = (640, 480)
        
        self._frame_count    = 0
        self._last_faces:    list[dict] = []   
        self._tracker        = FaceTracker()
        
        # Async state
        self._is_inf_running = False
        self._inf_lock       = threading.Lock()

        from core.state import global_signals
        global_signals.faiss_updated.connect(self._on_faiss_updated)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_target_size(self, width: int, height: int):
        if width > 0 and height > 0:
            self.target_size = (width, height)

    def stop(self):
        self.running = False
        self.wait()

    def _on_faiss_updated(self):
        """Flush recognition cache when FAISS index is rebuilt."""
        with self._inf_lock:
            self._last_faces = []

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        last_frame_time = 0.0
        is_active       = False
        frame_key       = f"stream:{self.client_id}:frame"

        while self.running:
            raw = cache.get(frame_key)

            if raw:
                frame = self._decode_frame(raw)
                if frame is None:
                    self.msleep(5)
                    continue

                last_frame_time = time.time()
                if not is_active:
                    is_active = True

                self._frame_count = (self._frame_count + 1) % 10_000
                
                # Non-blocking inference trigger
                if not self._is_inf_running and (self._frame_count % INFERENCE_THROTTLE == 0):
                    self._is_inf_running = True
                    # Launch inference in background thread
                    t = threading.Thread(
                        target=self._async_inf_worker, 
                        args=(frame.copy(),), 
                        daemon=True
                    )
                    t.start()

                # Always draw the LATEST known face bboxes
                # This ensures the video never pauses for AI "thinking"
                with self._inf_lock:
                    faces_to_draw = list(self._last_faces)

                self._draw_frame(frame, faces_to_draw)
                self._emit_frame(frame)

            else:
                if is_active and (time.time() - last_frame_time > 1.5):
                    is_active = False
                    self._tracker.clear()
                    self.stream_inactive.emit(self.client_id)

            self.msleep(5) # Higher frequency loop

    def _async_inf_worker(self, frame: np.ndarray):
        """Worker thread for AI + DB tasks."""
        try:
            results = self._run_inference(frame)
            with self._inf_lock:
                self._last_faces = results
        except Exception as e:
            print(f"VideoProcessor: Async Inference Error — {e}")
        finally:
            self._is_inf_running = False

    # ------------------------------------------------------------------
    # AI Logic (Runs in Background Thread)
    # ------------------------------------------------------------------

    def _run_inference(self, frame: np.ndarray) -> list[dict]:
        """
        Runs heavy InsightFace, MongoDB, and Redis tasks.
        """
        h, w      = frame.shape[:2]
        scale     = min(MAX_INFERENCE_SIZE / w, MAX_INFERENCE_SIZE / h)
        inf_frame = (cv2.resize(frame,
                               (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA)
                     if scale < 1.0 else frame)
        if scale >= 1.0:
            scale = 1.0

        raw_faces    = face_app.get(inf_frame)
        tracked      = self._tracker.update(raw_faces, scale)
        parsed_faces = []

        for item in tracked:
            track    = item["track"]
            track_id = item["track_id"]
            raw_face = item["raw_face"]
            
            bbox     = track.smoothed_bbox.astype(int)

            # Potential slow DB/Network call
            name, threat, meta = self._recognise(track, track_id)

            if meta and hasattr(raw_face, "pose"):
                aadhar = meta.get("aadhar")
                self._try_auto_augment(aadhar, raw_face)

            aadhr = meta.get("aadhar") if meta else None
            if aadhr:
                self._try_log(aadhr)
            if threat == "High":
                self._try_alert(name)

            parsed_faces.append({
                "bbox":  bbox,
                "name":  name,
                "threat": threat,
            })

        self._tracker.prune_stale()
        return parsed_faces

    def _recognise(self, track, track_id: int) -> tuple[str, str, dict | None]:
        """Return (name, threat_level, meta). Uses Redis cache first."""
        emb       = track.avg_embedding
        emb_hash  = hash(emb.tobytes()) & 0xFFFF_FFFF_FFFF_FFFF
        cache_key = f"cache:face:{emb_hash}"
        cached    = cache_str.get(cache_key)

        if cached:
            meta   = json.loads(cached)
            return meta.get("name", "Unknown"), meta.get("threat_level", "Low"), meta

        identity = watchdog.recognize_face(emb, threshold=FAISS_THRESHOLD)
        if identity:
            self.person_identified.emit(identity)
            cache_str.set(cache_key, json.dumps(identity), ex=int(FACE_CACHE_TTL_S))
            return identity.get("name", "Unknown"), identity.get("threat_level", "Low"), identity

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
        pose = face_obj.pose # [yaw, pitch, roll]
        if any(abs(angle) > AUTO_AUGMENT_TILT_DEG for angle in pose):
            lock_key = f"aug_lock:{aadhar}"
            if not cache_str.get(lock_key):
                watchdog.augment_identity(aadhar, face_obj.embedding)
                cache_str.set(lock_key, "1", ex=3600)

    # ------------------------------------------------------------------
    # Drawing & Transcoding
    # ------------------------------------------------------------------

    def _draw_frame(self, frame: np.ndarray, faces: list[dict]):
        for pf in faces:
            bbox  = pf["bbox"]
            name  = pf["name"]
            threat = pf["threat"]
            
            main_color   = (83, 83, 255) if threat == "High" else (200, 229, 0)
            text_color   = (255, 255, 255)
            
            cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), main_color, 1, cv2.LINE_AA)
            
            label = f" {name.upper()} "
            font = cv2.FONT_HERSHEY_DUPLEX
            font_scale = 0.5
            thickness = 1
            (tw, th), _ = cv2.getTextSize(label, font, font_scale, thickness)
            
            lx, ly = bbox[0], bbox[1] - 10
            cv2.rectangle(frame, (lx, ly - th - 5), (lx + tw, ly + 5), (15, 10, 8), -1)
            cv2.rectangle(frame, (lx, ly - th - 5), (lx + tw, ly + 5), main_color, 1, cv2.LINE_AA)
            cv2.putText(frame, label, (lx, ly), font, font_scale, text_color, thickness, cv2.LINE_AA)

    def _emit_frame(self, frame: np.ndarray):
        h, w        = frame.shape[:2]
        tw, th      = self.target_size
        scale       = min(tw / w, th / h)
        nw, nh      = int(w * scale), int(h * scale)
        out = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA) \
              if nw > 0 and nh > 0 else frame
        rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
        sh, sw, sc  = rgb.shape
        qt_img = QImage(rgb.data, sw, sh, sc * sw, QImage.Format.Format_RGB888)
        self.frame_ready.emit(qt_img.copy())

    @staticmethod
    def _decode_frame(raw: bytes) -> np.ndarray | None:
        try:
            arr   = np.frombuffer(raw, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None: return None
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            frame = cv2.flip(frame, 1)
            return frame
        except Exception:
            return None
