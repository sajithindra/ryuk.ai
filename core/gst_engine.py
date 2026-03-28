import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject, GLib
import threading
import time
import numpy as np
import cairo
import logging

# Initialize Gst
Gst.init(None)

logger = logging.getLogger("ryuk.gst")

class GstEngine:
    """
    High-performance GStreamer Pipeline for RTSP Ingestion & Cairo Overlays.
    Handles AI inference stream (BGR) and UI stream (MJPEG) in a single graph.
    """
    def __init__(self, client_id: str, rtsp_url: str, width: int = 640, height: int = 480):
        self.client_id = client_id
        self.rtsp_url = rtsp_url
        self.width = width
        self.height = height
        
        self.pipeline = None
        self.bus = None
        self.loop = None
        
        self._faces = {} # Dict: track_id or index -> {bbox, name, threat, ttl, alpha}
        self._lock = threading.Lock()
        
        self.latest_ui_frame = None
        self.latest_ai_frame = None
        
        self.is_running = False
        self._thread = None
        self._max_ttl = 15 # Persistent for 15 frames (~0.5s if 30fps)

    def start(self):
        """Starts the GStreamer pipeline in a background GLib loop."""
        # Pipeline Definition:
        # rtspsrc -> h264parse -> decodebin -> videoconvert -> BGRx
        # Tee -> 
        #   1. AI Branch: appsink (raw BGR)
        #   2. UI Branch: cairooverlay -> videoconvert -> jpegenc -> appsink (MJPEG)
        
        pipeline_str = (
            f"rtspsrc location={self.rtsp_url} latency=100 ! "
            f"rtph264depay ! h264parse ! decodebin ! videoconvert ! "
            f"video/x-raw,format=BGRx ! tee name=t "
            f"t. ! queue max-size-buffers=1 leaky=downstream ! videoconvert ! video/x-raw,format=BGR ! appsink name=ai_sink emit-signals=true "
            f"t. ! queue max-size-buffers=1 leaky=downstream ! cairooverlay name=ovl ! videoconvert ! jpegenc quality=85 ! appsink name=ui_sink emit-signals=true"
        )
        
        self.pipeline = Gst.parse_launch(pipeline_str)
        self.bus = self.pipeline.get_bus()
        
        # Connect Overlays
        overlay = self.pipeline.get_by_name("ovl")
        overlay.connect("draw", self._on_draw)
        
        # Connect Sinks
        ai_sink = self.pipeline.get_by_name("ai_sink")
        ai_sink.connect("new-sample", self._on_new_ai_sample)
        
        ui_sink = self.pipeline.get_by_name("ui_sink")
        ui_sink.connect("new-sample", self._on_new_ui_sample)
        
        self.is_running = True
        self.pipeline.set_state(Gst.State.PLAYING)
        
        # Run GMainLoop to handle signals
        self.loop = GLib.MainLoop()
        self._thread = threading.Thread(target=self.loop.run)
        self._thread.daemon = True
        self._thread.start()
        
        logger.info(f"GstEngine ({self.client_id}) — Pipeline started for {self.rtsp_url}")

    def stop(self):
        self.is_running = False
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        if self.loop:
            self.loop.quit()

    def update_faces(self, faces: list):
        """Standardize face objects for the cairo draw callback with persistence."""
        with self._lock:
            # We refresh the TTL of existing faces if detected again
            # To simplify, we'll use position or name+bbox to match or just clear if very different.
            # But here, we take 'faces' from Processor which ALREADY have tracking.
            # We'll use the 'track_id' if available, otherwise index.
            
            new_faces_map = {}
            for i, f in enumerate(faces):
                tid = f.get('track_id', f'idx_{i}')
                new_faces_map[tid] = {
                    'bbox': f.get('bbox'),
                    'name': f.get('name', 'Unknown'),
                    'threat': f.get('threat', 'Low'),
                    'ttl': self._max_ttl,
                    'is_new': True
                }
            
            # Merge with existing
            for tid, existing in list(self._faces.items()):
                if tid in new_faces_map:
                    # Update existing with new data
                    existing.update(new_faces_map[tid])
                else:
                    # Decaying phase
                    existing['ttl'] -= 1
                    existing['is_new'] = False
                    if existing['ttl'] <= 0:
                        del self._faces[tid]
            
            # Add totally new ones that weren't in existing
            for tid, new_f in new_faces_map.items():
                if tid not in self._faces:
                    self._faces[tid] = new_f

    def _on_draw(self, overlay, context, timestamp, duration):
        """Cairo Drawing Callback. Redesigned for Premium HUD Aesthetic."""
        with self._lock:
            # Create a localized copy and filter stale
            active_faces = {k: v.copy() for k, v in self._faces.items()}
            
        for tid, f in active_faces.items():
            bbox = f.get('bbox') # [x1, y1, x2, y2]
            name = f.get('name', 'Unknown')
            threat = f.get('threat', 'Low')
            ttl = f.get('ttl')
            
            # Calculate Alpha for persistent/fading effect
            # First few frames are solid, then fade out linearly.
            alpha = 1.0
            if ttl < 5:
                alpha = max(0.0, ttl / 5.0)

            # Modern Color Palette
            if threat == "High": r, g, b = (1.0, 0.1, 0.2) # Tech Red
            elif threat == "Medium": r, g, b = (1.0, 0.7, 0.0) # Tactical Orange
            else: r, g, b = (0.2, 1.0, 0.4) # Cyber Green

            x, y, x2, y2 = bbox
            w, h = x2 - x, y2 - y
            cor_len = min(w, h) * 0.2 # Corner length

            # 1. DRAW HUD CORNERS (Tactical Look)
            context.set_source_rgba(r, g, b, alpha * 0.8)
            context.set_line_width(1.5)
            
            # Top-Left
            context.move_to(x, y + cor_len); context.line_to(x, y); context.line_to(x + cor_len, y); context.stroke()
            # Top-Right
            context.move_to(x2 - cor_len, y); context.line_to(x2, y); context.line_to(x2, y + cor_len); context.stroke()
            # Bottom-Left
            context.move_to(x, y2 - cor_len); context.line_to(x, y2); context.line_to(x + cor_len, y2); context.stroke()
            # Bottom-Right
            context.move_to(x2 - cor_len, y2); context.line_to(x2, y2); context.line_to(x2, y2 - cor_len); context.stroke()
            
            # Sub-rectangle (very thin, subtle)
            context.set_line_width(0.5)
            context.set_source_rgba(r, g, b, alpha * 0.1)
            context.rectangle(x, y, w, h)
            context.stroke()

            # 2. GLASSMORPHISM LABEL
            label_h = 24
            label_y = y - label_h - 4
            if label_y < 10: label_y = y2 + 4 # Flip if off-top

            # Label Background (Translucent Gradient)
            context.set_source_rgba(0, 0, 0, alpha * 0.4)
            context.rectangle(x, label_y, w, label_h)
            context.fill()
            
            # Bottom accent bar
            context.set_source_rgba(r, g, b, alpha * 0.6)
            context.rectangle(x, label_y + label_h - 2, w, 2)
            context.fill()
            
            # 3. TYPOGRAPHY
            context.set_source_rgba(1, 1, 1, alpha * 0.95)
            context.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            context.set_font_size(11)
            
            text = f"{name.upper()} // {threat.upper()}"
            extents = context.text_extents(text)
            
            # Center text in label
            tx = x + (w - extents.width) / 2
            ty = label_y + (label_h + extents.height) / 2 - 2
            
            context.move_to(tx, ty)
            context.show_text(text)
            
            # 4. TARGETING HASH (Center of Face)
            if threat == "High":
                cx, cy = (x + x2)/2, (y + y2)/2
                context.set_source_rgba(r, g, b, alpha * (0.3 + 0.2 * np.sin(time.time() * 10))) # Pulsating
                context.set_line_width(1.0)
                context.move_to(cx - 5, cy); context.line_to(cx + 5, cy)
                context.move_to(cx, cy - 5); context.line_to(cx, cy + 5)
                context.stroke()


    def _on_new_ai_sample(self, sink):
        """Pulls raw BGR frame for AI processing."""
        sample = sink.emit("pull-sample")
        if not sample: return Gst.FlowReturn.OK
        
        buf = sample.get_buffer()
        caps = sample.get_caps()
        
        # Get Frame Data
        (result, map_info) = buf.map(Gst.MapFlags.READ)
        if result:
            try:
                # Assuming caps contain width/height
                s = caps.get_structure(0)
                w, h = s.get_value("width"), s.get_value("height")
                # format is BGR (3 bytes per pixel)
                frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((h, w, 3)).copy()
                self.latest_ai_frame = frame
            finally:
                buf.unmap(map_info)
                
        return Gst.FlowReturn.OK

    def _on_new_ui_sample(self, sink):
        """Pulls MJPEG encoded frame for UI streaming."""
        sample = sink.emit("pull-sample")
        if not sample: return Gst.FlowReturn.OK
        
        buf = sample.get_buffer()
        (result, map_info) = buf.map(Gst.MapFlags.READ)
        if result:
            try:
                self.latest_ui_frame = map_info.data
            finally:
                buf.unmap(map_info)
                
        return Gst.FlowReturn.OK
