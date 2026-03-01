"""
components/video_worker.py

VideoProcessor reads frames from Redis, delegates face tracking to
FaceTracker, runs recognition + alert logic, then emits QImage signals.

Refactored: the 150-line run() mega-method is now decomposed across:
  - FaceTracker   (components/face_tracker.py)  — track lifecycle
  - _run_inference()  — AI + recognition + alerting
  - _draw_frame()     — OpenCV overlay drawing
  - run()             — thin orchestration loop
"""
import time
import cv2
import numpy as np
import json

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
)


class VideoProcessor(QThread):
    """
    Background QThread:
      1. Pulls JPEG frames from Redis.
      2. Decodes and preprocesses.
      3. Every Nth frame: runs InsightFace + recognition + alert.
      4. Draws overlays.
      5. Emits QImage to the UI.
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
        self._last_faces:    list[dict] = []   # cached for throttled frames
        self._tracker        = FaceTracker()

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

    # ------------------------------------------------------------------
    # Qt slots
    # ------------------------------------------------------------------

    def _on_faiss_updated(self):
        """Flush recognition cache when FAISS index is rebuilt."""
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
                    self.msleep(10)
                    continue

                last_frame_time = time.time()
                if not is_active:
                    is_active = True

                # Inference on every Nth frame
                self._frame_count = (self._frame_count + 1) % 10_000
                if self._frame_count % INFERENCE_THROTTLE == 0:
                    self._tracker.prune_stale()
                    self._last_faces = self._run_inference(frame)

                self._draw_frame(frame, self._last_faces)
                self._emit_frame(frame)

            else:
                if is_active and (time.time() - last_frame_time > 1.5):
                    is_active = False
                    self._tracker.clear()
                    self.stream_inactive.emit(self.client_id)

            self.msleep(10)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_frame(raw: bytes) -> np.ndarray | None:
        """Decode JPEG bytes, rotate and flip for correct orientation."""
        try:
            arr   = np.frombuffer(raw, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                return None
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            frame = cv2.flip(frame, 1)
            return frame
        except Exception:
            return None

    def _run_inference(self, frame: np.ndarray) -> list[dict]:
        """
        Downscale → InsightFace → match tracks → recognise → alert.
        Returns list of face dicts ready for drawing.
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
            bbox     = item["bbox"]

            name, threat, meta = self._recognise(track, track_id)

            # Activity log + alert
            aadhr = meta.get("aadhar") if meta else None
            if aadhr:
                self._try_log(aadhr)
            if threat == "High":
                self._try_alert(name)

            parsed_faces.append({
                "bbox":  bbox,
                "name":  name,
                "threat": threat,
                "lmk2d": item["lmk2d"],
                "lmk3d": item["lmk3d"],
            })

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

        identity = watchdog.recognize_face(emb, threshold=0.45)
        if identity:
            self.person_identified.emit(identity)
            cache_str.set(cache_key, json.dumps(identity), ex=int(FACE_CACHE_TTL_S))
            return identity.get("name", "Unknown"), identity.get("threat_level", "Low"), identity

        return "Unknown", "Low", None

    def _try_log(self, aadhar: str):
        """Log activity if not in cooldown."""
        lock_key = f"log_lock:{aadhar}:{self.client_id}"
        if not cache_str.get(lock_key):
            watchdog.log_activity(aadhar, self.client_id)
            cache_str.set(lock_key, "1", ex=int(LOG_COOLDOWN_S))

    def _try_alert(self, name: str):
        """Publish high-threat alert if not in cooldown."""
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

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    @staticmethod
    def _draw_face_mesh(frame: np.ndarray,
                        points: np.ndarray,
                        color: tuple = (0, 255, 0)):
        size  = frame.shape
        rect  = (0, 0, size[1], size[0])
        sub   = cv2.Subdiv2D(rect)
        for p in points:
            if 0 <= p[0] < size[1] and 0 <= p[1] < size[0]:
                sub.insert((float(p[0]), float(p[1])))
        for t in sub.getTriangleList():
            pts = [(int(t[i]), int(t[i+1])) for i in range(0, 6, 2)]
            if all(0 <= pt[0] < size[1] and 0 <= pt[1] < size[0] for pt in pts):
                cv2.line(frame, pts[0], pts[1], color, 1, cv2.LINE_AA)
                cv2.line(frame, pts[1], pts[2], color, 1, cv2.LINE_AA)
                cv2.line(frame, pts[2], pts[0], color, 1, cv2.LINE_AA)

    def _draw_frame(self, frame: np.ndarray, faces: list[dict]):
        for pf in faces:
            bbox  = pf["bbox"]
            name  = pf["name"]
            threat = pf["threat"]
            cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]),
                          (255, 0, 0), 1)
            label_color = (0, 0, 255) if threat == "High" else (0, 255, 0)
            cv2.putText(frame, f"{name.upper()} ({threat})",
                        (bbox[0], bbox[1] - 15),
                        cv2.FONT_HERSHEY_DUPLEX, 0.7, label_color, 1)
            mesh_pts = []
            if pf["lmk2d"] is not None: mesh_pts.extend(pf["lmk2d"])
            if pf["lmk3d"] is not None: mesh_pts.extend(pf["lmk3d"])
            if mesh_pts:
                self._draw_face_mesh(frame, np.array(mesh_pts))

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
