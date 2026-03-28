import sys
import os
import numpy as np
import time

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock
# Mock all non-essential modules
sys.modules['motor'] = MagicMock()
sys.modules['motor.motor_asyncio'] = MagicMock()
sys.modules['qdarktheme'] = MagicMock()
sys.modules['nicegui'] = MagicMock()
sys.modules['redis'] = MagicMock()

from core.deep_sort import DeepSortTracker
from insightface.app.common import Face
import core.watchdog_indexer as watchdog
from config import FAISS_THRESHOLD

def test_instant_update():
    print("--- Step 1: Initialize Tracker and Indexer ---")
    tracker = DeepSortTracker()
    
    # Mock data
    aadhar = "1234-5678-9012"
    emb = np.random.rand(512).astype(np.float32)
    
    # 1. Enroll as "Low" threat
    print("Enrolling profile as LOW threat...")
    watchdog._indexer._faiss_index = None # Reset indexer
    watchdog._indexer._faiss_mapping = []
    
    # Manually populate mapping instead of full enrolment to keep it fast
    watchdog._indexer._faiss_mapping = [{"aadhar": aadhar, "name": "Test User", "threat_level": "Low"}]
    watchdog._indexer._aadhar_to_meta = {aadhar: watchdog._indexer._faiss_mapping[0]}
    # Mock FAISS search to always return index 0
    class MockIndex:
        def search(self, q, k): return np.array([[1.0]]), np.array([[0]])
        def add(self, x): pass
        @property
        def ntotal(self): return 1
    watchdog._indexer._faiss_index = MockIndex()

    # 2. Simulate first detection
    print("Simulating detection...")
    fake_face = Face(bbox=np.array([100, 100, 200, 200]), embedding=emb)
    tracker.predict()
    tracker.update([fake_face])
    
    # Process through a simplified engine loop
    from services.unified_engine import UnifiedInferenceEngine
    engine = UnifiedInferenceEngine()
    engine.trackers["test_client"] = tracker
    
    packet = {"client_id": "test_client", "frame": np.zeros((480, 640, 3), dtype=np.uint8)}
    result1 = engine.process_frame(packet)
    
    initial_threat = result1["recognition"][0]["threat_level"]
    print(f"Initial threat level in result: {initial_threat}")
    assert initial_threat == "Low"

    # 3. UPDATE PROFILE TO HIGH
    print("\n--- Step 2: Update Profile to HIGH ---")
    # Simulate WatchdogIndexer.update_profile / update_index
    watchdog._indexer._faiss_mapping[0]["threat_level"] = "High"
    watchdog._indexer._aadhar_to_meta[aadhar]["threat_level"] = "High"
    
    # 4. Simulate next frame (No detection - Tracking only)
    print("Processing next frame (Tracking-Only)...")
    # Manually ensure we skip detection by setting frame count to 1 and interval to 5
    engine.frame_counts["test_client"] = 1
    
    result2 = engine.process_frame(packet)
    
    updated_threat = result2["recognition"][0]["threat_level"]
    print(f"Updated threat level in result: {updated_threat}")
    
    if updated_threat == "High":
        print("\nSUCCESS: Profile update reflected instantaneously in active track!")
    else:
        print("\nFAILURE: Profile update lagged or was not reflected.")
        sys.exit(1)

if __name__ == "__main__":
    test_instant_update()
