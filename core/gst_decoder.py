import subprocess
import shlex
import numpy as np
import threading
import time
import os
from typing import Optional

class GstDecoder:
    """
    Manages a GStreamer subprocess for low-latency, hardware-accelerated decoding.
    Optimized for RTSP streams.
    """
    def __init__(self, 
                 width: int = 1280, 
                 height: int = 720, 
                 pix_fmt: str = "BGR"):
        self.width = width
        self.height = height
        self.pix_fmt = pix_fmt # GStreamer format (e.g., BGR, RGB, I420)
        self.frame_size = width * height * 3 # Assuming BGR24
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self.running = False
        
        # Auto-detect best decoder
        self.decoder_plugin = self._detect_best_decoder()
        print(f"DEBUG: GstDecoder — Selected plugin: {self.decoder_plugin}")

    def _detect_best_decoder(self) -> str:
        """Checks for available hardware decoders."""
        try:
            plugins = subprocess.check_output("gst-inspect-1.0", shell=True).decode()
            if "nvh264dec" in plugins:
                return "nvh264dec"
            elif "vaapih264dec" in plugins:
                return "vaapih264dec"
            elif "avdec_h264" in plugins:
                return "avdec_h264"
        except:
            pass
        return "decodebin"

    def start(self, source: str):
        """
        Starts the GStreamer process for an RTSP source.
        """
        with self._lock:
            if self.proc: return
            
            # Optimized pipeline for low latency
            # - rtspsrc latency=0: minimize buffering
            # - drop-on-latency=true: discard frames if late
            # - sync=false: don't block on timestamps (maximize FPS)
            
        # Optimized DeepStream-style pipeline:
        # 1. Force TCP to avoid "breaking" artifacts (UDP packet loss)
        # 2. Add jitter buffer (latency) to absorb network spikes
        # 3. Add queues after each major component to decouple stages
        if self.decoder_plugin == "vaapih264dec":
            # VA-API path: use vaapipostproc for fast GPU scaling/format conversion
            pipeline = (
                f"rtspsrc location={source} latency=200 protocols=tcp ! "
                f"rtph264depay ! h264parse ! queue max-size-buffers=30 ! "
                f"vaapih264dec ! vaapipostproc width={self.width} height={self.height} format=bgrx ! "
                f"videoconvert ! video/x-raw,format={self.pix_fmt} ! fdsink sync=false"
            )
        else:
            # NVIDIA/Generic path: add queues and ensures low-latency parse
            pipeline = (
                f"rtspsrc location={source} latency=200 protocols=tcp ! "
                f"rtph264depay ! h264parse ! queue max-size-buffers=30 ! "
                f"{self.decoder_plugin} ! queue ! "
                f"videoscale method=0 ! video/x-raw,width={self.width},height={self.height} ! "
                f"videoconvert ! video/x-raw,format={self.pix_fmt} ! fdsink sync=false"
            )
            
            cmd = f"gst-launch-1.0 -q {pipeline}"
            print(f"DEBUG: GstDecoder — Running: {cmd}")
            
            self.proc = subprocess.Popen(
                shlex.split(cmd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=10**7
            )
            self.running = True

            # Error logging thread
            def log_errors():
                if self.proc and self.proc.stderr:
                    for line in iter(self.proc.stderr.readline, b''):
                        print(f"[GStreamer-GstDecoder] {line.decode().strip()}")
            
            threading.Thread(target=log_errors, daemon=True).start()

    def stop(self):
        """Stops the GStreamer process gracefully."""
        with self._lock:
            self.running = False
            if self.proc:
                try:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait()
                except Exception:
                    pass
                self.proc = None

    def read_frame(self) -> Optional[np.ndarray]:
        """Reads a decoded BGR frame from GStreamer stdout."""
        if not self.proc or not self.proc.stdout: return None
        try:
            chunks = []
            bytes_read = 0
            while bytes_read < self.frame_size:
                needed = self.frame_size - bytes_read
                chunk = self.proc.stdout.read(needed)
                if not chunk: # EOF or error
                    return None
                chunks.append(chunk)
                bytes_read += len(chunk)
            
            raw = b"".join(chunks)
            return np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3))
        except Exception as e:
            if self.running:
                print(f"GstDecoder Read Error: {e}")
            return None

    def restart(self, source: str):
        self.stop()
        self.start(source)
