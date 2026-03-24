import os
import torch
import numpy as np
import cv2
from fast_alpr import ALPR
from core.logger import logger

class PlateDetector:
    def __init__(self, model_path=None, conf_threshold=0.4, device='auto'):
        """
        Initialize the PlateDetector using FastALPR.
        """
        # FastALPR manages its own model downloads and hub integration
        # Mapping 'cuda' to 'auto' for FastALPR compatibility if needed
        ocr_device = 'cuda' if torch.cuda.is_available() and device != 'cpu' else 'cpu'
        
        try:
            self.model = ALPR(
                detector_conf_thresh=conf_threshold,
                ocr_device=ocr_device
            )
            logger.info(f"FastALPR initialized on {ocr_device}")
        except Exception as e:
            logger.error(f"Failed to initialize FastALPR: {e}")
            raise e

    def detect(self, frame):
        """
        Detect and recognize license plates in a single frame.
        Returns: list of dicts with bbox, conf, label, and ocr_text
        """
        try:
            print(f"DEBUG: Running FastALPR.predict on frame...", flush=True)
            results = self.model.predict(frame)
            detections = []
            for res in results:
                bbox = res.detection.bounding_box
                # FastALPR bounding box is [x1, y1, x2, y2]
                box = [bbox.x1, bbox.y1, bbox.x2, bbox.y2]
                
                det = {
                    "bbox": box,
                    "confidence": float(res.detection.confidence),
                    "label": "License Plate",
                    "ocr_text": res.ocr.text if res.ocr else None,
                    "ocr_conf": res.ocr.confidence if res.ocr else 0.0,
                }
                detections.append(det)
            return detections
        except Exception as e:
            logger.error(f"FastALPR detection error: {e}")
            return []

    def detect_batch(self, frames):
        """
        Detect license plates in a batch of frames.
        Note: FastALPR predict currently handles single frames or paths.
        Implement batching by iterating if native batching is absent.
        """
        batch_results = []
        for frame in frames:
            batch_results.append(self.detect(frame))
        return batch_results
