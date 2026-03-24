import os
import cv2
import numpy as np
import torch
from fast_alpr import ALPR
from core.logger import logger

def test_alpr():
    print("--- Ryuk AI ALPR Diagnostic ---")
    print(f"CUDA Available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"Device: {torch.cuda.get_device_name(0)}")
    
    print("\nAttempting to initialize FastALPR...")
    try:
        alpr = ALPR(
            detector_conf_thresh=0.2, # Lower for testing
            ocr_device='cuda' if torch.cuda.is_available() else 'cpu'
        )
        print("Success: FastALPR initialized.")
    except Exception as e:
        print(f"FAILED: FastALPR initialization error: {e}")
        return

    # Create a dummy image or find one
    dummy_frame = np.zeros((640, 640, 3), dtype=np.uint8)
    cv2.putText(dummy_frame, "PLATE TEST", (100, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    
    print("\nRunning prediction on dummy frame...")
    try:
        results = alpr.predict(dummy_frame)
        print(f"Prediction count: {len(results)}")
        for i, res in enumerate(results):
            print(f" Result {i}: {res.detection.bounding_box} | Conf: {res.detection.confidence}")
            if res.ocr:
                print(f" OCR: {res.ocr.text} | Conf: {res.ocr.confidence}")
    except Exception as e:
        print(f"FAILED: Prediction error: {e}")

if __name__ == "__main__":
    test_alpr()
