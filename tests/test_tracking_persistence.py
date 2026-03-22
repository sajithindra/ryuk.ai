import sys
import os
import numpy as np
import time

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.deep_sort import DeepSortTracker
from insightface.app.common import Face
import config

def test_tracking_persistence():
    tracker = DeepSortTracker()
    
    # 1. Simulate a face detection
    print("--- Step 1: Detect Face ---")
    bbox1 = np.array([100, 100, 200, 200])
    emb1 = np.random.rand(512).astype(np.float32)
    fake_face = Face(bbox=bbox1, embedding=emb1)
    
    tracker.update([fake_face])
    track_id = list(tracker.tracks.keys())[0]
    track = tracker.tracks[track_id]
    print(f"Track created: ID={track_id}, State={track.state} (0=Tentative, 1=Confirmed)")
    
    # 2. Age it to confirm (N_INIT=3)
    for _ in range(2):
        tracker.predict()
        tracker.update([fake_face])
    print(f"Track state after {config.TRACKER_N_INIT} hits: {track.state}")
    
    # 3. Pin an identity
    track.pinned_identity = {"name": "Sajith", "threat_level": "Low"}
    print(f"Pinned identity: {track.pinned_identity['name']}")
    
    # 4. Simulate Occlusion (No detections for 60 frames -> 2 seconds at 30fps)
    print("\n--- Step 2: Occlusion (60 frames) ---")
    for i in range(60):
        tracker.predict()
        tracker.update([])
        if i % 10 == 0:
            print(f"Frame {i}: Track {track_id} exists={track_id in tracker.tracks}, time_since_update={track.time_since_update}")
            
    print(f"After 60 frames occlusion: Track {track_id} exists={track_id in tracker.tracks}")
    
    # 5. Recovery: Face reappears slightly moved
    print("\n--- Step 3: Recovery ---")
    bbox2 = np.array([110, 110, 210, 210]) # Slight movement
    fake_face2 = Face(bbox=bbox2, embedding=emb1)
    
    tracker.predict()
    tracker.update([fake_face2])
    
    new_tracks = list(tracker.tracks.keys())
    print(f"Active tracks after recovery: {new_tracks}")
    
    if track_id in tracker.tracks:
        recovered_track = tracker.tracks[track_id]
        print(f"SUCCESS: Track {track_id} recovered!")
        print(f"Pinned identity retained: {recovered_track.pinned_identity['name'] if recovered_track.pinned_identity else 'None'}")
    else:
        print("FAILURE: Track lost during occlusion.")

if __name__ == "__main__":
    test_tracking_persistence()
