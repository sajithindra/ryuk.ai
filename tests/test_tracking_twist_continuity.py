import numpy as np
import time
from core.deep_sort import DeepSortTracker
from config import FACE_TRACK_MAX_DIST

def test_tracking_spatial_continuity():
    """
    Verifies that a track persists even if the bbox jumps significantly (up to 400px).
    """
    tracker = DeepSortTracker()
    
    # 1. Initial detection
    # [x1, y1, x2, y2]
    bbox1 = np.array([100, 100, 200, 200])
    emb1 = np.random.rand(512).astype(np.float32)
    
    tracker.update([{"bbox": bbox1, "embedding": emb1}])
    assert len(tracker.tracks) == 1
    track_id = list(tracker.tracks.keys())[0]
    print(f"Created track {track_id}")
    
    # 2. Simulate a jump of 300 pixels (exceeds old 200 threshold)
    # Center moves from (150, 150) to (450, 150) -> dist = 300
    bbox2 = np.array([400, 100, 500, 200])
    emb2 = emb1.copy() # Same identity
    
    # Call predict first as the pipeline would
    tracker.predict()
    
    # Update with jumped bbox
    tracker.update([{"bbox": bbox2, "embedding": emb2}])
    
    # Verify it matched the same track
    assert len(tracker.tracks) == 1
    assert track_id in tracker.tracks
    assert tracker.tracks[track_id].time_since_update == 0
    print(f"Track {track_id} persisted after 300px jump.")

def test_tracking_damping_momentum():
    """
    Verifies that velocity is NOT damped aggressively after short gaps (e.g. 10 frames).
    """
    tracker = DeepSortTracker()
    
    # Initial detection moving right
    bbox = np.array([100, 100, 200, 200])
    tracker.update([{"bbox": bbox}])
    
    tid = list(tracker.tracks.keys())[0]
    track = tracker.tracks[tid]
    
    # Give it some velocity
    track.kf.x[4] = 10.0 # dx1 = 10
    
    # Simulate 10 frames of prediction (occlusion/skip)
    for _ in range(10):
        tracker.predict()
        
    # Verify velocity is still high (damping starts at 30)
    assert abs(track.kf.x[4] - 10.0) < 0.1
    print(f"Velocity maintained after 10 frames: {track.kf.x[4]}")
    
    # Simulate 40 frames total
    for _ in range(30):
        tracker.predict()
        
    # Now it should be damped
    assert track.kf.x[4] < 8.0
    print(f"Velocity damped after 40 frames: {track.kf.x[4]}")

if __name__ == "__main__":
    try:
        test_tracking_spatial_continuity()
        test_tracking_damping_momentum()
        print("\nSUCCESS: Tracking continuity tests passed.")
    except Exception as e:
        print(f"\nFAILURE: {e}")
        exit(1)
