import subprocess
import shlex
import numpy as np
import threading
import time
import os
from typing import Optional

class HwDecoder:
    """
    Manages an FFmpeg subprocess for hardware-accelerated decoding (NVDEC).
    Can decode both stream-based (RTSP) and packet-based (JPEG) inputs.
    """
    def __init__(self, 
                 width: int, 
                 height: int, 
                 codec: str = "mjpeg_cuvid", 
                 input_format: str = "mjpeg",
                 pix_fmt: str = "bgr24"):
        self.width = width
        self.height = height
        self.codec = codec
        self.input_format = input_format
        self.pix_fmt = pix_fmt
        self.frame_size = width * height * 3
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self.running = False

    def start(self, source: str = "pipe:0", extra_input_args: str = ""):
        """
        Starts the FFmpeg process. 
        If source is 'pipe:0', it expects raw bytes via write().
        """
        with self._lock:
            if self.proc: return
            
            # 1. Input Flags Integration
            # For RTSP/Network streams, we inject low-latency probesize/analyzeduration if not provided
            if source.startswith(("rtsp://", "http://", "https://", "rtmp://")):
                input_flags = "-probesize 128000 -analyzeduration 100000 -rtsp_transport tcp "
            else:
                input_flags = ""
            
            input_flags += f"{extra_input_args} "
            input_fmt_args = f"-f {self.input_format}" if source == "pipe:0" and self.input_format else ""
            
            # 2. Filter Integration (Scaling to target resolution)
            # This allows starting FFmpeg WITHOUT knowing source resolution, by forcing output resolution.
            filter_args = f"-vf scale={self.width}:{self.height}"
            
            cmd = (
                f"ffmpeg -y -hide_banner -loglevel error "
                f"{input_flags} {input_fmt_args} -c:v {self.codec} -i {source} "
                f"{filter_args} -f rawvideo -pix_fmt {self.pix_fmt} -"
            )
            
            self.proc = subprocess.Popen(
                shlex.split(cmd),
                stdin=subprocess.PIPE if source == "pipe:0" else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, # Capture errors for debugging
                bufsize=10**7
            )
            self.running = True

            # Error logging thread
            def log_errors():
                if self.proc and self.proc.stderr:
                    for line in iter(self.proc.stderr.readline, b''):
                        print(f"[FFmpeg-HwDecoder] {line.decode().strip()}")
            
            threading.Thread(target=log_errors, daemon=True).start()

    def stop(self):
        with self._lock:
            if self.proc:
                self.running = False
                try:
                    if self.proc.stdin:
                        self.proc.stdin.close()
                    self.proc.kill()
                    self.proc.wait(timeout=1.0)
                except Exception:
                    pass
                self.proc = None

    def write(self, data: bytes):
        """Writes compressed frame data to FFmpeg stdin."""
        if not self.proc or not self.proc.stdin: return
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        except Exception as e:
            print(f"HwDecoder Write Error: {e}")
            self.restart()

    def read_frame(self) -> Optional[np.ndarray]:
        """Reads a decoded frame from FFmpeg stdout."""
        if not self.proc or not self.proc.stdout: return None
        try:
            chunks = []
            bytes_read = 0
            while bytes_read < self.frame_size:
                needed = self.frame_size - bytes_read
                chunk = self.proc.stdout.read(needed)
                if not chunk: # EOF
                    return None
                chunks.append(chunk)
                bytes_read += len(chunk)
            
            raw = b"".join(chunks)
            return np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3))
        except Exception as e:
            if self.running:
                print(f"HwDecoder Read Error: {e}")
            return None

    def restart(self, source: str = "pipe:0"):
        self.stop()
        self.start(source)

class JpegBatchDecoder:
    """
    Optimized for decoding individual JPEGs using NVDEC by keeping the FFmpeg 
    process alive and feeding it via stdin.
    """
    def __init__(self, width: int, height: int):
        self.decoder = HwDecoder(width, height, codec="mjpeg_cuvid", input_format="mjpeg")
        self.decoder.start()

    def decode(self, jpeg_bytes: bytes) -> Optional[np.ndarray]:
        self.decoder.write(jpeg_bytes)
        return self.decoder.read_frame()

    def stop(self):
        self.decoder.stop()
