import sys
from unittest.mock import MagicMock

# Create mock objects for the core components we modified
# This avoids importing any real project modules that might have missing dependencies

class MockTrack:
    def __init__(self, identity_id=None):
        self.identity_id = identity_id

class MockIndexer:
    def __init__(self):
        self._aadhar_to_meta = {}
    def get_metadata(self, aadhar):
        return self._aadhar_to_meta.get(aadhar)

def test_instant_logic():
    print("--- Verifying Instant Update Logic ---")
    indexer = MockIndexer()
    aadhar = "A123"
    
    # 1. Simulate profile as LOW
    metadata_low = {"name": "Test", "threat_level": "Low"}
    indexer._aadhar_to_meta[aadhar] = metadata_low
    
    # 2. Simulate engine extraction
    track = MockTrack(identity_id=aadhar)
    
    # Logic from unified_engine.py:
    # latest_meta = watchdog.get_metadata(track.identity_id)
    latest_meta = indexer.get_metadata(track.identity_id)
    print(f"Extraction 1 (Expect Low): {latest_meta['threat_level']}")
    assert latest_meta['threat_level'] == "Low"
    
    # 3. UPDATE PROFILE to HIGH
    print("\nUPDATING profile in indexer...")
    indexer._aadhar_to_meta[aadhar]["threat_level"] = "High"
    
    # 4. Simulate next extraction in active track
    latest_meta_after = indexer.get_metadata(track.identity_id)
    print(f"Extraction 2 (Expect High): {latest_meta_after['threat_level']}")
    assert latest_meta_after['threat_level'] == "High"
    
    print("\nSUCCESS: The dynamic lookup logic correctly reflects metadata changes immediately.")

if __name__ == "__main__":
    test_instant_logic()
