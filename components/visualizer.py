import cv2
import numpy as np
from typing import List, Dict

class Visualizer:
    def __init__(self):
        from config import VIDEO_DRAW_THICKNESS_SCALE, VIDEO_FONT_SCALE_BASE
        self.thickness_scale = VIDEO_DRAW_THICKNESS_SCALE
        self.font_scale_base = VIDEO_FONT_SCALE_BASE
        self.font = cv2.FONT_HERSHEY_DUPLEX
        self.bg_color = (10, 8, 5)
        self.text_color = (255, 255, 255)
        
        self.colors = {
            "High":    (83,  83,  255),   # Red — threat
            "Medium":  (0,  140,  255),   # Orange — caution
            "Low":     (83,  222,  83),   # Green — safe
            "Unknown": (120, 120, 120),   # Grey — unidentified
        }

    def draw_detections(self, frame: np.ndarray, faces: List[Dict]):
        if frame is None or frame.size == 0:
            return
            
        h, w = frame.shape[:2]
        if h == 0 or w == 0:
            return
            
        base_thickness = max(1, int(w / self.thickness_scale))
        font_scale = max(0.35, w / self.font_scale_base)
        text_thickness = max(1, int(base_thickness / 2))

        for pf in faces:
            try:
                bbox_raw = pf.get("bbox")
                if bbox_raw is None:
                    continue
                    
                # Ensure bbox is a valid int array
                bbox = np.array(bbox_raw, dtype=float).flatten()
                if len(bbox) < 4:
                    continue
                x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
                
                # Clamp to frame bounds
                x1, x2 = max(0, x1), min(w, x2)
                y1, y2 = max(0, y1), min(h, y2)
                
                # Skip degenerate boxes
                if x2 - x1 < 10 or y2 - y1 < 10:
                    continue
                    
                name = str(pf.get("name", "Unknown")).upper()
                threat = pf.get("threat", "Low") if name != "UNKNOWN" else "Unknown"
                main_color = self.colors.get(threat, self.colors["Low"])

                # Draw Bounding Box
                cv2.rectangle(frame, (x1, y1), (x2, y2), main_color, base_thickness, cv2.LINE_4)
                
                label = f" {name} "
                (tw, th), _ = cv2.getTextSize(label, self.font, font_scale, text_thickness)
                
                # Position label above box, or below if too close to top
                lx = max(0, min(x1, w - tw))
                ly = y1 - base_thickness - 5
                if ly < th + 5:
                    ly = y1 + th + base_thickness + 5
                
                # Draw Label Background and Text
                cv2.rectangle(frame, (lx, ly - th - 3), (lx + tw, ly + 3), self.bg_color, -1)
                cv2.rectangle(frame, (lx, ly - th - 3), (lx + tw, ly + 3), main_color, 1, cv2.LINE_4)
                cv2.putText(frame, label, (lx, ly), self.font, font_scale, self.text_color, text_thickness, cv2.LINE_4)
            except Exception:
                continue  # Never crash the display loop
