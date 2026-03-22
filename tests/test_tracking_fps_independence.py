import sys
import os
import numpy as np
import time

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.deep_sort import DeepSortTracker
from insightface.app.common import Face
import config

def test_tracking_fps_independence():
    tracker = DeepSortTracker()
    
    print("--- Step 1: Detect and Confirm Face ---")
    bbox1 = np.array([100, 100, 200, 200])
    emb1 = np.random.rand(512).astype(np.float32)
    fake_face = Face(bbox=bbox1, embedding=emb1)
    
    # Confirm track (N_INIT=3)
    for _ in range(3):
        tracker.predict()
        tracker.update([fake_face])
    
    track_id = list(tracker.tracks.keys())[0]
    track = tracker.tracks[track_id]
    print(f"Track {track_id} confirmed. State={track.state}")

    # Now simulate a scenario where we have many predicts (30fps) but very few updates (e.g. occlusion)
    # We want to make sure it doesn't get deleted just because of frame count.
    
    print("\n--- Step 2: Simulate Occlusion for 5 seconds ---")
    # In the old logic, if TRACKER_MAX_AGE was 30 (for 1s at 30fps), it would die after 1s.
    # Here, TRACKER_MAX_AGE is 300 (10s), so we need to test beyond that if we want to be sure.
    # But let's just verify it survives 5 seconds regardless of frame ticks.
    
    # We will call predict() 150 times (5s at 30fps)
    start_time = time.time()
    for i in range(150):
        tracker.predict()
        tracker.update([]) # No detections
        
    elapsed = time.time() - start_time
    print(f"Elapsed: {elapsed:.2f}s, Ticks (time_since_update): {track.time_since_update}")
    print(f"Track {track_id} exists={track_id in tracker.tracks}")
    
    if track_id in tracker.tracks:
        print("SUCCESS: Track survived 5s (even if frame ticks were high)")
    else:
        print("FAILURE: Track deleted prematurely")

    # Step 3: Wait until it actually expires (>10s)
    print("\n--- Step 3: Wait for real-time expiration (>10s) ---")
    # Manually backdate the last_update_time to simulate 11s pass
    track.last_update_time -= 11.0
    
    tracker.predict()
    tracker.update([])
    
    if track_id not in tracker.tracks:
        print("SUCCESS: Track expired correctly based on real-time")
    else:
        print(f"FAILURE: Track still exists after 11s! (is_stale={track.is_stale})")

if __name__ == "__main__":
    test_tracking_fps_independence()
