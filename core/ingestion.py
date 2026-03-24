import time
import threading
import cv2
import numpy as np
import queue
from typing import Optional, Dict

class BaseIngestor:
    def __init__(self, client_id: str, source_url: Optional[str] = None):
        self.client_id = client_id
        self.source_url = source_url
        self.running = False
        self._latest_frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def read_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            frame = self._latest_frame
            self._latest_frame = None
            return frame

class GstIngestor(BaseIngestor):
    def __init__(self, client_id: str, source_url: str):
        super().__init__(client_id, source_url)
        from core.gst_decoder import GstDecoder
        self.decoder = GstDecoder(1280, 720)
        self._thread: Optional[threading.Thread] = None

    def start(self):
        super().start()
        self.decoder.start(self.source_url)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        super().stop()
        self.decoder.stop()

    def _run(self):
        while self.running:
            frame = self.decoder.read_frame()
            if frame is None:
                if not self.running: break
                print(f"DEBUG: GstIngestor ({self.client_id}) - Read Break. Retrying...")
                self.decoder.restart(self.source_url)
                time.sleep(1.0)
                continue
            with self._lock:
                self._latest_frame = frame

class HwIngestor(BaseIngestor):
    def __init__(self, client_id: str, source_url: str):
        super().__init__(client_id, source_url)
        from core.hw_decoder import HwDecoder
        from config import RTSP_LOW_LATENCY_FLAGS
        extra_args = " ".join([f"-{f.replace('+', ' ')}" for f in RTSP_LOW_LATENCY_FLAGS])
        self.decoder = HwDecoder(1280, 720, codec="h264_cuvid")
        self.extra_args = extra_args
        self._thread: Optional[threading.Thread] = None

    def start(self):
        super().start()
        self.decoder.start(source=self.source_url, extra_input_args=self.extra_args)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        super().stop()
        self.decoder.stop()

    def _run(self):
        while self.running:
            frame = self.decoder.read_frame()
            if frame is None:
                if not self.running: break
                print(f"DEBUG: HwIngestor ({self.client_id}) - Read Break. Retrying...")
                self.decoder.restart(self.source_url)
                time.sleep(1.0)
                continue
            with self._lock:
                self._latest_frame = frame

class CvIngestor(BaseIngestor):
    def __init__(self, client_id: str, source_url: str):
        super().__init__(client_id, source_url)
        self.cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        super().start()
        import os
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|strict;experimental"
        self.cap = cv2.VideoCapture(self.source_url, cv2.CAP_FFMPEG)
        if not self.cap.isOpened():
            print(f"DEBUG: CvIngestor ({self.client_id}) - FAILED TO OPEN RTSP STREAM: {self.source_url}")
            return
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        super().stop()
        if self.cap:
            self.cap.release()

    def _run(self):
        while self.running:
            if not self.cap.grab():
                time.sleep(1.0)
                self.cap.open(self.source_url, cv2.CAP_FFMPEG)
                continue
            
            ret, frame = self.cap.retrieve()
            if ret:
                with self._lock:
                    self._latest_frame = frame
            else:
                time.sleep(0.001)

class RedisIngestor(BaseIngestor):
    def __init__(self, client_id: str):
        super().__init__(client_id)
        from core.state import cache
        self.cache = cache
        self.sub_key = f"stream:{client_id}:sub:frame"
        self.legacy_key = f"stream:{client_id}:frame"
        self.jpeg_hw_decoder = None

    def read_frame(self) -> Optional[np.ndarray]:
        raw_sub = self.cache.get(self.sub_key) or self.cache.get(self.legacy_key)
        if not raw_sub:
            return None

        from config import USE_FFMPEG_CUDA
        if USE_FFMPEG_CUDA:
            if self.jpeg_hw_decoder is None:
                # Auto-detect resolution from first frame (CPU decode once)
                temp_frame = self._decode_frame_cpu(raw_sub)
                if temp_frame is not None:
                    h_sub, w_sub = temp_frame.shape[:2]
                    from core.hw_decoder import JpegBatchDecoder
                    self.jpeg_hw_decoder = JpegBatchDecoder(w_sub, h_sub)
                    return temp_frame
            else:
                return self.jpeg_hw_decoder.decode(raw_sub)
        return self._decode_frame_cpu(raw_sub)

    def _decode_frame_cpu(self, raw: bytes) -> Optional[np.ndarray]:
        try:
            arr = np.frombuffer(raw, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None: return None
            
            h, w = frame.shape[:2]
            if w > 1280 or h > 1280:
                scale = 1280 / max(w, h)
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
            return frame
        except Exception:
            return None

    def stop(self):
        super().stop()
        if self.jpeg_hw_decoder:
            self.jpeg_hw_decoder.stop()

def get_ingestor(client_id: str, source_url: Optional[str] = None) -> BaseIngestor:
    from config import USE_GSTREAMER, USE_FFMPEG_CUDA
    if source_url:
        if USE_GSTREAMER:
            return GstIngestor(client_id, source_url)
        elif USE_FFMPEG_CUDA:
            return HwIngestor(client_id, source_url)
        else:
            return CvIngestor(client_id, source_url)
    else:
        return RedisIngestor(client_id)
