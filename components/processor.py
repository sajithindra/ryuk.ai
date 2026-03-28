import time
import cv2
import numpy as np
import json
import threading
import os
import queue
import subprocess
import shlex
from typing import Callable, List, Dict, Optional

from core.state import cache, cache_str
import core.serialization as serde
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
    USE_FFMPEG_CUDA,
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
        self._inf_queue = queue.Queue(maxsize=1)
        self._inf_lock = threading.Lock()
        
        self.latest_processed_frame: Optional[bytes] = None
        
        # Callbacks for detections (Multiple Listeners Support)
        self.listeners = set() # Set of objects with on_detection, on_stream_start, on_inactive
        
        # Start persistent result poller
        self._result_worker_thread = threading.Thread(target=self._pipeline_result_worker, daemon=True)
        self._result_worker_thread.start()
        
        self._last_ui_update = 0.0

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self._ffmpeg_proc_ref = None # Store reference for stop()

    def stop(self):
        self.running = False
        if hasattr(self, '_ffmpeg_proc_ref') and self._ffmpeg_proc_ref:
            try:
                # _ffmpeg_proc_ref is an HwDecoder instance, call its stop() method
                self._ffmpeg_proc_ref.stop()
            except:
                pass

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
        """Main Processor Loop — Handles Frame Ingress and Result Rendering."""
        last_frame_time = time.time()
        last_inf_time = 0.0
        is_active = False
        
        # GStreamer Engine (for RTSP)
        gst = None
        if self.source_url:
            from core.gst_engine import GstEngine
            # Initialize GStreamer Pipeline
            gst = GstEngine(self.client_id, self.source_url)
            gst.start()
            self._ffmpeg_proc_ref = gst # For stop()
        
        # Legacy/Redis Logic Keys
        sub_key = f"stream:{self.client_id}:sub:frame"
        legacy_key = f"stream:{self.client_id}:frame"
        
        while self.running:
            frame = None
            
            # 1. PULL FRAME
            if gst:
                # GStreamer Case (RTSP)
                frame = gst.latest_ai_frame
            else:
                # Redis Case (Push-based)
                raw_sub = cache.get(sub_key) or cache.get(legacy_key)
                if raw_sub:
                    frame = self._decode_frame(raw_sub)
            
            if frame is None:
                time.sleep(0.001) # Idle CPU saver
                # Inactivity Check
                if is_active and (time.time() - last_frame_time > 10.0):
                    is_active = False
                    with self._inf_lock:
                        self._tracker.clear()
                        for l in list(self.listeners):
                            if hasattr(l, 'on_inactive'):
                                l.on_inactive(self.client_id)
                continue

            # 2. MANAGE STATE
            if not is_active:
                is_active = True
                with self._inf_lock:
                    for l in list(self.listeners):
                        if hasattr(l, 'on_stream_start'):
                            l.on_stream_start(self.client_id)
            
            self._frame_count = (self._frame_count + 1) % 10_000
            last_frame_time = time.time()

            # 3. PUSH TO INFERENCE (Throttled)
            if self._frame_count % INFERENCE_THROTTLE == 0:
                self._push_to_redis(frame)

            # 4. TRACKING & METADATA
            with self._inf_lock:
                self._tracker.predict()
                
            faces_to_draw = []
            detections_to_sync = []
            now = time.time()
            # UI Refresh rate
            should_sync_ui = (now - self._last_ui_update > 0.5)
            
            with self._inf_lock:
                for tid, track in list(self._tracker._tracks.items()):
                    if track.is_stale: continue
                    
                    # Identity Lookup
                    name, threat, meta = "Unknown", "Low", None
                    if track.identity_id:
                        meta = watchdog.get_metadata(track.identity_id)
                        if meta:
                            name = meta.get("name", "Unknown")
                            threat = meta.get("threat_level", "Low")
                    
                    # Sync to UI Sidebar
                    if should_sync_ui and meta and "aadhar" in meta:
                        detections_to_sync.append(meta)
                    
                    # Filter Visual Bounding Box (Ghost Mitigation)
                    if track.time_since_update <= 10: # ~1s visibility
                        faces_to_draw.append({
                            "track_id": tid,
                            "bbox": track.smoothed_bbox.astype(int),
                            "name": name,
                            "threat": threat
                        })

            if should_sync_ui:
                self._last_ui_update = now
                if detections_to_sync:
                    for l in list(self.listeners):
                        if hasattr(l, 'on_detection'):
                            l.on_detection({'client_id': self.client_id, 'detections': detections_to_sync})

            # 5. RENDER OVERLAYS
            if gst:
                # OFF-LOAD TO PIPELINE (Zero-copy Cairo)
                gst.update_faces(faces_to_draw)
                self.latest_processed_frame = gst.latest_ui_frame
            else:
                # Fallback to OpenCV drawing for Redis/Web sources
                self._draw_frame(frame, faces_to_draw)
                self.latest_processed_frame = self._encode_frame(frame)

        # 6. CLEANUP
        if gst:
            gst.stop()

    def _push_to_redis(self, frame: np.ndarray):
        """Encapsulated Redis Ingestion Logic."""
        try:
            packet = {
                "client_id": self.client_id,
                "frame_count": self._frame_count,
                "timestamp": time.time(),
                "frame": frame.copy()
            }
            # We use rpush for the ingestion queue
            cache.rpush("ryuk:ingest", serde.pack(packet))
            # Limit queue size to prevent blowup if services are down
            if cache.llen("ryuk:ingest") > 100:
                cache.lpop("ryuk:ingest")
        except Exception as e:
            print(f"DEBUG: Processor ({self.client_id}) — Failed to push to pipeline: {e}")

    def _pipeline_result_worker(self):
        """Polls Redis for latest pipeline results and updates tracker."""
        res_key = f"stream:{self.client_id}:results"
        print(f"DEBUG: Processor ({self.client_id}) — Result worker started on {res_key}")
        
        while True:
            try:
                # We poll the results key. 
                # Alternative: Use Redis Pub/Sub for lower latency notifications
                raw_res = cache.blpop(res_key, timeout=1)
                if raw_res:
                    _, data = raw_res
                    packet = serde.unpack(data)
                    if not packet:
                        continue
                        
                    faces = packet.get('faces', [])
                    recognition = packet.get('recognition', [])
                    
                    if packet.get('frame_count', 0) % 20 == 0:
                         print(f"DEBUG: Processor ({self.client_id}) — Received Result Packet (Faces: {len(faces)})")
                    
                    # We need to map recognition (identities) back to face objects
                    # so tracker can see them.
                    for i, face in enumerate(faces):
                        if i < len(recognition):
                            if isinstance(face, dict):
                                face['ident_meta'] = recognition[i]
                            else:
                                face.ident_meta = recognition[i]

                    with self._inf_lock:
                        # Trackers update() logic expects raw_faces (list of insightface.Face)
                        # and scale (inf_frame to original frame).
                        # In our packet, bboxes are already scaled to original? 
                        # No, let's check detector.py.
                        # detector.py takes frame as is. If Processor sends scaled frame, it's scaled.
                        # Processor sends 'frame.copy()' from main loop.
                        # Main loop 'frame' is native resolution (e.g. 1080p).
                        # So scale in tracker.update should be 1.0.
                        tracked = self._tracker.update(faces, inf_scale=1.0)
                        
                        # Apply identity logic similar to _run_inference but decoupled
                        for item in tracked:
                            track = item["track"]
                            raw_face = item["raw_face"] 
                            
                            # Support both dict access (from msgpack) and attribute access (Face object)
                            if isinstance(raw_face, dict):
                                meta = raw_face.get("ident_meta")
                            else:
                                meta = getattr(raw_face, "ident_meta", None)
                                
                            # PIN IDENTITY: Store the unique identifier (Aadhar)
                            if meta and meta.get("aadhar") and meta.get("aadhar") != "Unknown":
                                track.identity_id = meta["aadhar"]

                            # Signal UI listeners
                            if meta and "aadhar" in meta:
                                for l in list(self.listeners):
                                    if hasattr(l, 'on_detection'):
                                        l.on_detection({'client_id': self.client_id, 'detections': [meta]})
                
                # Sleep to prevent tight loop
                time.sleep(0.05)
                
            except Exception as e:
                print(f"DEBUG: Processor ({self.client_id}) — Result Worker Error: {e}")
                time.sleep(1)


    def _draw_frame(self, frame: np.ndarray, faces: List[Dict]):
        from config import VIDEO_DRAW_THICKNESS_SCALE, VIDEO_FONT_SCALE_BASE
        h, w = frame.shape[:2]
        # Responsive thickness: on 4k (3840w), thinner than 2 would be invisible.
        base_thickness = max(1, int(w / VIDEO_DRAW_THICKNESS_SCALE))
        
        # Responsive font scaling: at 1600px width, font_scale is ~1.0
        font_scale = w / VIDEO_FONT_SCALE_BASE
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

            # Draw Bounding Box - Use LINE_4 for speed over LINE_AA
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
        from config import VIDEO_JPEG_QUALITY
        try:
            # Quality balance between bandwidth and speed
            res, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), VIDEO_JPEG_QUALITY])
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
                # Use INTER_LINEAR for better quality/speed compromise than NEAREST
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)

            # frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            # frame = cv2.flip(frame, 1)
            return frame
        except Exception:
            return None
