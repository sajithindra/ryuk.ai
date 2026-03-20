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
        
        # Start persistent worker (it will wait for .start() to set running=True)
        self._inf_worker_thread = threading.Thread(target=self._persistent_inf_worker, daemon=True)
        self._inf_worker_thread.start()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self._ffmpeg_proc_ref = None # Store reference for stop()

    def stop(self):
        self.running = False
        if hasattr(self, '_ffmpeg_proc_ref') and self._ffmpeg_proc_ref:
            try:
                self._ffmpeg_proc_ref.terminate()
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
        frame_key = f"stream:{self.client_id}:frame"
        
        # Pull model (RTSP) vs Push model (Redis)
        cap = None
        grabber_thread = None
        ffmpeg_proc = None
        latest_frame_data = {"frame": None, "lock": threading.Lock(), "running": True}

        if self.source_url:
            if USE_FFMPEG_CUDA:
                # 1. Dynamic Resolution Discovery via ffprobe
                try:
                    probe_cmd = f"ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 {shlex.quote(self.source_url)}"
                    res_raw = subprocess.check_output(shlex.split(probe_cmd), timeout=5).decode().strip()
                    native_w, native_h = map(int, res_raw.split('x'))
                    print(f"DEBUG: Processor ({self.client_id}) — Auto-detected Stream Resolution: {native_w}x{native_h}")
                except Exception as e:
                    print(f"DEBUG: Processor ({self.client_id}) — Resolution discovery failed: {e}. Falling back to 1080p.")
                    native_w, native_h = 1920, 1080

                print(f"DEBUG: Processor ({self.client_id}) — Launching FFmpeg CUDA Decoder Pipe: {self.source_url}")
                # FFmpeg command for GPU decoding (NVDEC) at NATIVE resolution
                # Removed scale_cuda=640:640 to allow full quality display
                cmd = (
                    f"ffmpeg -hwaccel cuda -hwaccel_output_format cuda -rtsp_transport tcp "
                    f"-i {shlex.quote(self.source_url)} "
                    f"-vf 'hwdownload,format=nv12,format=bgr24' "
                    f"-f rawvideo -pix_fmt bgr24 -"
                )
                
                ffmpeg_proc = subprocess.Popen(
                    shlex.split(cmd), 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.DEVNULL,
                    bufsize=10**7
                )
                self._ffmpeg_proc_ref = ffmpeg_proc # Save reference for stop()
                
                # We use native resolution for display/drawing, 
                # but we'll scale to 640x640 later just for inference.
                w, h = native_w, native_h 
                
            else:
                print(f"DEBUG: Processor ({self.client_id}) - Opening RTSP stream (OpenCV Backend): {self.source_url}")
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|strict;experimental"
                cap = cv2.VideoCapture(self.source_url, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    print(f"DEBUG: Processor ({self.client_id}) - FAILED TO OPEN RTSP STREAM")
                    return
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            def grabber():
                nonlocal ffmpeg_proc
                if ffmpeg_proc:
                    # Use discovered native resolution
                    frame_size = w * h * 3
                    
                    while self.running and latest_frame_data["running"]:
                        raw_frame = ffmpeg_proc.stdout.read(frame_size)
                        if not raw_frame or len(raw_frame) != frame_size:
                            print(f"DEBUG: Processor ({self.client_id}) - FFmpeg Pipe Break. Retrying...")
                            ffmpeg_proc.terminate()
                            time.sleep(1.0)
                            ffmpeg_proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                            continue
                        
                        frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((h, w, 3))
                        
                        with latest_frame_data["lock"]:
                            latest_frame_data["frame"] = frame.copy()
                else:
                    # Original OpenCV grabber
                    while self.running and latest_frame_data["running"]:
                        if not cap.grab():
                            print(f"DEBUG: Processor ({self.client_id}) - RTSP Grab Failed. Retrying...")
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

        while self.running:
            frame = None
            
            if self.source_url:
                with latest_frame_data["lock"]:
                    frame = latest_frame_data["frame"]
                    latest_frame_data["frame"] = None # Consume
                
                if frame is None:
                    # Optional: print(f"DEBUG: Processor ({self.client_id}) - Waiting for frame...")
                    time.sleep(0.001) # Ultra-short sleep
                    continue
                
                # Debug: Frame received
                # print(f"DEBUG: Processor ({self.client_id}) - Consumed frame for processing.")
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
                    try:
                        # Non-blocking put. If queue full, older frame is still being processed
                        self._inf_queue.put_nowait(frame.copy())
                    except queue.Full:
                        pass
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
                            
                        # Prioritize pinned_identity for life-of-track stability
                        meta = track.pinned_identity if track.pinned_identity else track.id_cache
                        
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
        if ffmpeg_proc:
            ffmpeg_proc.terminate()
            ffmpeg_proc.wait(timeout=1.0)

    def _persistent_inf_worker(self):
        """Persistent worker thread to avoid the overhead of spawning new threads."""
        while True: # Keep thread alive for entire app lifecycle
            try:
                inf_frame = self._inf_queue.get(timeout=1.0)
            except queue.Empty:
                continue
                
            if inf_frame is not None:
                try:
                    self._is_inf_running = True
                    # Run AI in background
                    start_time = time.time()
                    self._run_inference(inf_frame)
                    latency = (time.time() - start_time) * 1000
                    print(f"PERF: Processor ({self.client_id}) — GPU Inference Complete: {latency:.2f}ms")
                except Exception as e:
                    print(f"Processor ({self.client_id}): AI Worker Error — {e}")
                finally:
                    self._is_inf_running = False

    def _run_inference(self, frame: np.ndarray) -> List[Dict]:
        from config import MAX_INFERENCE_SIZE
        h, w = frame.shape[:2]
        # Optimize: MAX_INFERENCE_SIZE (typically 640px) is the sweet spot for buffalo_l GPU compute
        scale = min(MAX_INFERENCE_SIZE / w, MAX_INFERENCE_SIZE / h)
        inf_frame = (cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
                     if scale != 1.0 else frame)
        if scale >= 1.0:
            scale = 1.0

        raw_faces = face_app.get(inf_frame)
        
        # CPU OPTIMIZATION: Removed 180-degree rotation fallback. 
        # Running inference twice per frame when no faces are detected is extremely 
        # expensive and was likely causing significant CPU spikes.
        
        with self._inf_lock:
            tracked = self._tracker.update(raw_faces, scale)
            parsed_faces = []

            for item in tracked:
                track = item["track"]
                track_id = item["track_id"]
                raw_face = item["raw_face"]
                bbox = track.smoothed_bbox.astype(int)

                # STICKY IDENTITY: If already pinned, skip recognition to save CPU/prevent flicker
                if track.pinned_identity:
                    name = track.pinned_identity.get("name", "Unknown")
                    threat = track.pinned_identity.get("threat_level", "Low")
                    meta = track.pinned_identity
                else:
                    name, threat, meta = self._recognise(track, track_id)
                    # PIN: If we successfully recognized them, lock it to this track
                    if meta and meta.get("name") != "Unknown":
                        track.pinned_identity = meta

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
