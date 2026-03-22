import time
import cv2
import numpy as np
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai_processor import face_app
from components.face_tracker import FaceTracker
from config import INFERENCE_THROTTLE, FRAME_SKIP

def verify_perf():
    print("--- Pipeline Performance Verification ---")
    print(f"Inference Throttle: {INFERENCE_THROTTLE}")
    
    # Create a dummy frame
    frame = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
    
    tracker = FaceTracker()
    
    # Measure Detection + Embedding (Full Pipeline)
    start = time.time()
    faces = face_app.get(frame)
    full_latency = (time.time() - start) * 1000
    print(f"Full Detection + Recognition Latency: {full_latency:.2f}ms")
    
    # Measure Tracking (Prediction Only)
    start = time.time()
    tracker.predict()
    track_latency = (time.time() - start) * 1000
    print(f"Tracking (Prediction) Latency: {track_latency:.4f}ms")
    
    # Simulate a sequence of 300 frames (roughly 10 seconds of 30fps)
    total_start = time.time()
    inf_count = 0
    proc_count = 0
    for i in range(1, 301):
        if i % FRAME_SKIP == 0:
            faces = face_app.get(frame)
            tracker.update(faces, 1.0)
            inf_count += 1
            proc_count += 1
        else:
            # In real system, we don't even predict tracker positions for skipped frames
            # because we don't draw them.
            pass
            
    total_time = (time.time() - total_start) * 1000
    avg_per_frame = total_time / 300
    
    print(f"\nSimulation Result (300 frames):")
    print(f"Frame Skip: {FRAME_SKIP}")
    print(f"Total Time: {total_time:.2f}ms")
    print(f"Avg Time per physical frame: {avg_per_frame:.2f}ms")
    print(f"Total Processed Frames: {proc_count}")
    print(f"Total AI Inferences: {inf_count}")
    
    # Estimate savings compared to processing EVERY frame (INFERENCE_THROTTLE=1, FRAME_SKIP=1)
    # Old baseline: 300 * full_latency
    old_baseline = 300 * full_latency
    savings = (1.0 - total_time / old_baseline) * 100
    print(f"\nEstimated Compute Savings vs 30FPS Detection: {savings:.2f}%")
    
    if savings > 70:
        print("\nSUCCESS: Compute reduction > 70% threshold reached!")
    else:
        print("\nWARNING: Compute reduction below 70% target.")

if __name__ == "__main__":
    verify_perf()
