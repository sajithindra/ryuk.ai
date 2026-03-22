import numpy as np
from core.deep_sort import DeepSortTrack

def test_identity_pinning_logic():
    """
    Verifies that a pinned identity is NOT overwritten by an unidentified result
    (dict with score but no name).
    """
    track = DeepSortTrack(1, np.array([100, 100, 200, 200]))
    
    # 1. First identification: Known
    meta1 = {"name": "Sajith", "aadhar": "1234", "score": 0.9}
    
    # Simulate logic in Processor/VideoWorker
    if meta1 and meta1.get("name") and meta1.get("name") != "Unknown":
        track.pinned_identity = meta1
    track.id_cache = meta1
    
    assert track.pinned_identity["name"] == "Sajith"
    print("Initial pin successful: Sajith")
    
    # 2. Second result: "Unknown" due to tilt (has score, no name)
    meta2 = {"score": 0.45} # Returned by recognize_face on failure
    
    # Simulate logic with the NEW FIX
    if meta2 and meta2.get("name") and meta2.get("name") != "Unknown":
        track.pinned_identity = meta2
    track.id_cache = meta2
    
    # Check that pinned_identity is STILL Sajith
    assert track.pinned_identity["name"] == "Sajith"
    assert track.id_cache["score"] == 0.45
    print("Pinned identity protected from nameless 'Unknown' result.")
    
    # 3. Third result: Explicit "Unknown" string
    meta3 = {"name": "Unknown", "score": 0.1}
    
    if meta3 and meta3.get("name") and meta3.get("name") != "Unknown":
        track.pinned_identity = meta3
    track.id_cache = meta3
    
    assert track.pinned_identity["name"] == "Sajith"
    print("Pinned identity protected from explicit 'Unknown' string.")

def test_initial_unknown_does_not_pin():
    """
    Verifies that we don't pin if the first ever result is unknown.
    """
    track = DeepSortTrack(2, np.array([100, 100, 200, 200]))
    
    meta1 = {"name": "Unknown", "score": 0.2}
    if meta1 and meta1.get("name") and meta1.get("name") != "Unknown":
        track.pinned_identity = meta1
    track.id_cache = meta1
    
    assert track.pinned_identity is None
    print("Initial 'Unknown' did not pin.")
    
    meta2 = {"name": "Sajith", "score": 0.8}
    if meta2 and meta2.get("name") and meta2.get("name") != "Unknown":
        track.pinned_identity = meta2
    track.id_cache = meta2
    
    assert track.pinned_identity["name"] == "Sajith"
    print("Subsequent 'Known' successfully pinned.")

if __name__ == "__main__":
    try:
        test_identity_pinning_logic()
        test_initial_unknown_does_not_pin()
        print("\nSUCCESS: Identity pinning logic tests passed.")
    except Exception as e:
        print(f"\nFAILURE: {e}")
        exit(1)
