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
        self._last_objects: List[Dict] = []
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
        last_frame_time = 0.0
        is_active = False
        
        # Substream/Main Stream split logic
        sub_key = f"stream:{self.client_id}:sub:frame"
        main_key = f"stream:{self.client_id}:main:frame"
        legacy_key = f"stream:{self.client_id}:frame"
        
        # Pull model (RTSP) vs Push model (Redis)
        cap = None
        grabber_thread = None
        hw_decoder = None
        cap = None
        latest_frame_data = {"frame": None, "lock": threading.Lock(), "running": True}
        ffmpeg_proc = None # Critical fix for cleanup NameError

        if self.source_url:
            if USE_FFMPEG_CUDA:
                # 1. Dynamic Resolution Discovery via ffprobe
                try:
                    probe_cmd = f"ffprobe -v error -rtsp_transport tcp -rtsp_flags prefer_tcp -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 {shlex.quote(self.source_url)}"
                    res_raw = subprocess.check_output(shlex.split(probe_cmd), timeout=5).decode().strip()
                    native_w, native_h = map(int, res_raw.split('x'))
                    print(f"DEBUG: Processor ({self.client_id}) — Auto-detected Stream Resolution: {native_w}x{native_h}")
                except Exception as e:
                    print(f"DEBUG: Processor ({self.client_id}) — Resolution discovery failed: {e}. Falling back to 1080p.")
                    native_w, native_h = 1920, 1080

                print(f"DEBUG: Processor ({self.client_id}) — Launching HwDecoder for RTSP: {self.source_url}")
                from core.hw_decoder import HwDecoder
                hw_decoder = HwDecoder(native_w, native_h, codec="h264_cuvid")
                hw_decoder.start(source=self.source_url)
                self._ffmpeg_proc_ref = hw_decoder # Save for stop()
                w, h = native_w, native_h
                
            else:
                print(f"DEBUG: Processor ({self.client_id}) - Opening RTSP stream (OpenCV Backend): {self.source_url}")
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|strict;experimental"
                cap = cv2.VideoCapture(self.source_url, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    print(f"DEBUG: Processor ({self.client_id}) - FAILED TO OPEN RTSP STREAM: {self.source_url}")
                    return
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            def grabber():
                if hw_decoder:
                    while self.running and latest_frame_data["running"]:
                        frame = hw_decoder.read_frame()
                        if frame is None:
                            print(f"DEBUG: Processor ({self.client_id}) - HwDecoder Read Break. Retrying...")
                            hw_decoder.restart(source=self.source_url)
                            time.sleep(1.0)
                            continue
                        
                        with latest_frame_data["lock"]:
                            latest_frame_data["frame"] = frame.copy()
                else:
                    while self.running and latest_frame_data["running"]:
                        if not cap.grab():
                            time.sleep(1.0)
                            cap.open(self.source_url, cv2.CAP_FFMPEG)
                            continue
                        
                        with latest_frame_data["lock"]:
                            needs_new_frame = latest_frame_data["frame"] is None
                        
                        if needs_new_frame:
                            ret, frame = cap.retrieve()
                            if ret:
                                with latest_frame_data["lock"]:
                                    latest_frame_data["frame"] = frame
                        else:
                            time.sleep(0.001)
            
            grabber_thread = threading.Thread(target=grabber, daemon=True)
            grabber_thread.start()

        # Redis-based JPEG Decoder (NVDEC)
        jpeg_hw_decoder = None

        while self.running:
            frame = None
            
            if self.source_url:
                with latest_frame_data["lock"]:
                    frame = latest_frame_data["frame"]
                    latest_frame_data["frame"] = None # Consume
                
                if frame is None:
                    time.sleep(0.001)
                    continue
            else:
                # Optimized Redis Pull with Substream/Main split
                # Processor (this class) is primarily for UI display, so it pulls SUBSTREAM
                raw_sub = cache.get(sub_key) or cache.get(legacy_key)
                if raw_sub:
                    if USE_FFMPEG_CUDA:
                        if jpeg_hw_decoder is None:
                            # Auto-detect resolution from first frame (CPU decode once)
                            temp_frame = self._decode_frame(raw_sub)
                            if temp_frame is not None:
                                h_sub, w_sub = temp_frame.shape[:2]
                                from core.hw_decoder import JpegBatchDecoder
                                jpeg_hw_decoder = JpegBatchDecoder(w_sub, h_sub)
                                frame = temp_frame
                        else:
                            frame = jpeg_hw_decoder.decode(raw_sub)
                    else:
                        frame = self._decode_frame(raw_sub)
                
                if frame is None:
                    if self._frame_count % 100 == 0:
                        print(f"DEBUG: Processor ({self.client_id}) - Waiting for Redis frame: {sub_key}")
            
            if frame is not None:
                if not is_active:
                    is_active = True
                    with self._inf_lock:
                        for l in list(self.listeners):
                            if hasattr(l, 'on_stream_start'):
                                print(f"DEBUG: Processor ({self.client_id}) — Notifying listener on_stream_start")
                                l.on_stream_start(self.client_id)

                self._frame_count = (self._frame_count + 1) % 10_000
                
                # Push to Micro-Pipeline (Non-blocking)
                # Optimization: Only push to ingestion if we are the primary source (RTSP).
                # WebSocket streams are already pushed by StreamingServer (core/server.py).
                if self.source_url and self._frame_count % INFERENCE_THROTTLE == 0:
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
                
                with self._inf_lock:
                    self._tracker.predict()

                # Get latest track states for drawing (Skip stale ones for real-time responsiveness)
                faces_to_draw = []
                detections_to_sync = []
                now = time.time()
                should_sync_ui = (now - self._last_ui_update > 1.0)
                
                with self._inf_lock:
                    for tid, track in list(self._tracker._tracks.items()):
                        # Skip if stale even if not yet pruned by background thread
                        if track.is_stale:
                            continue
                            
                        # Prioritize pinned_identity for life-of-track stability
                        name, threat, meta = self._get_cached_identity(track)
                        
                        # Sync identified tracks to UI listeners to keep cards alive
                        if should_sync_ui and meta and "aadhar" in meta:
                            detections_to_sync.append(meta)
                        
                        faces_to_draw.append({
                            "bbox": track.smoothed_bbox.astype(int),
                            "name": name,
                            "threat": threat,
                            "label": track.label,
                            "is_identified": track.is_identified or (track.pinned_identity is not None)
                        })

                if should_sync_ui:
                    self._last_ui_update = now
                    if detections_to_sync:
                        for l in list(self.listeners):
                            if hasattr(l, 'on_detection'):
                                l.on_detection({'client_id': self.client_id, 'detections': detections_to_sync})

                # Objects for synchronization (filtered)
                if should_sync_ui:
                    high_interest = ["person", "car", "motorcycle", "bicycle", "bus", "truck", "bag", "backpack", "suitcase"]
                    objects_to_sync = [o for o in self._last_objects if o["label"].lower() in high_interest]
                    if objects_to_sync:
                         for l in list(self.listeners):
                            if hasattr(l, 'on_object_detection'):
                                l.on_object_detection({'client_id': self.client_id, 'objects': objects_to_sync})

                self._draw_frame(frame, faces_to_draw, self._last_objects)
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
        if 'ffmpeg_proc' in locals() and ffmpeg_proc:
            ffmpeg_proc.terminate()
            ffmpeg_proc.wait(timeout=1.0)

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
                    objects = packet.get('objects', [])
                    
                    self._last_objects = objects
                    
                    if packet.get('frame_count', 0) % 20 == 0:
                         print(f"DEBUG: Processor ({self.client_id}) — Received Result Packet (Faces: {len(faces)}, Objects: {len(objects)})")
                    
                    # Combined detection list for the tracker
                    tracker_input = []
                    
                    # 1. Map identities to persons if provided in original objects list
                    # (Note: services/unified_engine.py now returns 'objects' with 'name' and 'is_identified')
                    for obj in objects:
                        tracker_input.append({
                            'bbox': obj['bbox'],
                            'label': obj.get('label', 'person'),
                            'ident_meta': {
                                'name': obj.get('name', 'Unknown'),
                                'threat_level': obj.get('threat_level', 'Low'),
                                'is_identified': obj.get('is_identified', False)
                            }
                        })
                        
                    # 2. Add standalone faces (legacy or auxiliary)
                    for i, face in enumerate(faces):
                        meta = recognition[i] if i < len(recognition) else None
                        tracker_input.append({
                            'bbox': face.bbox if hasattr(face, 'bbox') else face.get('bbox'),
                            'label': 'face',
                            'embedding': getattr(face, 'embedding', None),
                            'ident_meta': meta
                        })

                    with self._inf_lock:
                        # Tracker update supports multi-class with the new DeepSortTracker
                        tracked = self._tracker.update(tracker_input, inf_scale=1.0)
                        
                        for item in tracked:
                            track = item["track"]
                            raw_data = item.get("raw_face") # This is now our dict from tracker_input
                            
                            meta = raw_data.get("ident_meta") if isinstance(raw_data, dict) else None
                            
                            if meta and meta.get("name") and meta.get("name") != "Unknown":
                                track.pinned_identity = meta
                                track.is_identified = meta.get("is_identified", True)
                            
                            track.id_cache = meta

                            # Signal UI listeners for identified individuals
                            if meta and meta.get("aadhar"):
                                for l in list(self.listeners):
                                    if hasattr(l, 'on_detection'):
                                        l.on_detection({'client_id': self.client_id, 'detections': [meta]})
                
                # Sleep to prevent tight loop
                time.sleep(0.05)
                
            except Exception as e:
                print(f"DEBUG: Processor ({self.client_id}) — Result Worker Error: {e}")
                time.sleep(1)

    def _get_cached_identity(self, track) -> tuple[str, str, dict | None]:
        """Helper to get name/threat from track cache or last AI results."""
        if track.pinned_identity:
            return track.pinned_identity.get("name", "Unknown"), \
                   track.pinned_identity.get("threat_level", "Low"), \
                   track.pinned_identity

        if track.id_cache:
            return track.id_cache.get("name", "Unknown"), \
                   track.id_cache.get("threat_level", "Low"), \
                   track.id_cache

        return "Unknown", "Low", None

    def _draw_frame(self, frame: np.ndarray, faces: List[Dict], objects: List[Dict] = None):
        from config import VIDEO_DRAW_THICKNESS_SCALE, VIDEO_FONT_SCALE_BASE
        h, w = frame.shape[:2]
        # Responsive thickness: on 4k (3840w), thinner than 2 would be invisible.
        base_thickness = max(1, int(w / VIDEO_DRAW_THICKNESS_SCALE))
        
        # Responsive font scaling: at 1600px width, font_scale is ~1.0
        font_scale = h / 640.0 # Standardize scale to reference height
        font_scale = max(0.4, font_scale) 
        text_thickness = max(1, int(base_thickness / 2))

        # Color palette
        COLORS = {
            "High": (83, 83, 255),    # Terracotta/Red
            "Medium": (0, 140, 255),  # Tactical Orange
            "Low": (83, 222, 83),     # Safe Green
            "Object": (255, 120, 0),  # Vivid Cyber Blue (BGR)
            "Text": (255, 255, 255),
            "BG": (10, 8, 5)
        }

        # 1. Draw General Objects
        if objects:
            for obj in objects:
                label = obj["label"].lower()
                
                # Skip drawing 'person' as a generic object since it's handled in the specialized section below
                if label == "person":
                    continue

                bbox = [int(v) for v in obj["bbox"]]
                conf = obj.get("confidence", 0.0)
                
                # Draw box with responsive thickness
                cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), COLORS["Object"], base_thickness, cv2.LINE_4)
                
                # Small label
                txt = f"{obj['label'].upper()} {int(conf*100)}%" if conf > 0 else obj['label'].upper()
                font = cv2.FONT_HERSHEY_SIMPLEX
                (tw, th), bl = cv2.getTextSize(txt, font, font_scale * 0.6, text_thickness)
                
                lx, ly = bbox[0], bbox[1] - 5
                if ly < th: ly = bbox[1] + th + 5
                
                # Background rect for readability
                cv2.rectangle(frame, (lx, ly - th - 2), (lx + tw, ly + 2), COLORS["BG"], -1)
                cv2.putText(frame, txt, (lx, ly), font, font_scale * 0.6, COLORS["Object"], text_thickness, cv2.LINE_4)

        # 2. Draw Faces (Higher Priority)
        # 2. Draw Active Tracks (Faces & Persons)
        for pf in faces:
            bbox = pf["bbox"]
            name = pf["name"]
            threat = pf["threat"]
            label = pf.get("label", "face")
            is_identified = pf.get("is_identified", False)
            
            # Person tracks use larger, solid boxes. Faces use thinner accent boxes.
            if label == "person":
                color_map = {
                    "High": (83, 83, 255),
                    "Medium": (0, 140, 255),
                    "Low": (83, 222, 83)
                }
                main_color = color_map.get(threat, (200, 200, 200))
                
                # Double thickness for identified persons
                thickness = base_thickness + (1 if is_identified else 0)
                
                # Draw main body box
                cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), main_color, thickness, cv2.LINE_4)
                
                # If identified, add a status indicator
                if is_identified:
                    cv2.circle(frame, (bbox[0] + 15, bbox[1] + 15), 5, main_color, -1)
            else:
                # Face boxes (accents)
                main_color = (255, 255, 255) if threat == "Low" else (83, 83, 255)
                cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), main_color, 1, cv2.LINE_4)

            # Draw Label
            display_name = f" {name.upper()} " if name != "Unknown" else f" {label.upper()} "
            font = cv2.FONT_HERSHEY_DUPLEX
            
            (tw, th), baseline = cv2.getTextSize(display_name, font, font_scale, text_thickness)
            
            lx = bbox[0]
            ly = bbox[1] - base_thickness - 5
            if ly < th + 5:
                ly = bbox[1] + th + base_thickness + 5
            
            if lx + tw > w: lx = w - tw
            lx = max(0, lx)

            # Draw Label Background and Text
            cv2.rectangle(frame, (lx, ly - th - 3), (lx + tw, ly + 3), (10, 8, 5), -1)
            cv2.rectangle(frame, (lx, ly - th - 3), (lx + tw, ly + 3), main_color, 1, cv2.LINE_4)
            cv2.putText(frame, display_name, (lx, ly), font, font_scale, (255, 255, 255), text_thickness, cv2.LINE_4)

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
