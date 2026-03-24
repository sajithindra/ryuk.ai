import os
import sys

# Add project root to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from core.bootstrap import bootstrap_gpu
bootstrap_gpu()

# ============================================================================
# Normal imports — GPU libs are now resolvable by the dynamic linker
# ============================================================================
import time
import json


import core.watchdog_indexer as watchdog
from core.state import cache, cache_str
from config import ALERT_COOLDOWN_S, LOG_COOLDOWN_S
import core.serialization as serde

def run_sink_service():
    print("=" * 60)
    print("RYUK AI — SINK SERVICE (LOGGING & ALERTER)")
    print("=" * 60)
    
    print("\n[READY] Waiting for FAISS stream ('ryuk:faiss')...")
    
    while True:
        try:
            packed = cache.blpop("ryuk:faiss", timeout=1)
            if not packed:
                continue
            
            _, data = packed
            packet = serde.unpack(data)
            
            if not packet:
                continue
            
            recognition = packet.get('recognition', [])
            client_id = packet.get('client_id')
            
            if not recognition:
                # No faces identified, still push the packet for UI to clear boxes
                res_key = f"stream:{client_id}:results"
                cache.rpush(res_key, serde.pack(packet))
                cache.ltrim(res_key, -5, -1) # Keep only 5 recent results to avoid memory leaks
                continue
                
            start_time = time.time()
            
            for i, res in enumerate(recognition):
                if not res or 'name' not in res:
                    continue
                
                name = res.get('name', 'Unknown')
                threat = res.get('threat_level', 'Low')
                aadhar = res.get('aadhar')
                
                if aadhar and name != "Unknown":
                    # 1. Activity Logging (with cooldown)
                    lock_key = f"log_lock:{aadhar}:{client_id}"
                    if not cache_str.get(lock_key):
                        watchdog.log_activity(aadhar, client_id)
                        cache_str.set(lock_key, "1", ex=int(LOG_COOLDOWN_S))
                        
                    # 2. Auto-Augmentation (Frontal face update)
                    faces = packet.get('faces', [])
                    if i < len(faces):
                        face_obj = faces[i]
                        pose = face_obj.get("pose", [0, 0, 0])
                        # If pose is stable (near zero), augment
                        if all(abs(angle) < 15 for angle in pose):
                            aug_lock = f"aug_lock:{aadhar}"
                            if not cache_str.get(aug_lock):
                                watchdog.augment_identity(aadhar, face_obj.get('embedding'))
                                cache_str.set(aug_lock, "1", ex=3600)
                
                # 3. Intelligence & Security Alerts
                if aadhar:
                    # Publish to real-time feed for dashboard
                    msg_data = {
                        "type": "SECURITY_ALERT" if threat == "High" else "INTEL_UPDATE",
                        "message": f"{name} identified at {client_id}",
                        "name": name,
                        "aadhar": aadhar,
                        "threat_level": threat,
                        "source": client_id,
                        "timestamp": time.time(),
                    }
                    
                    # High priority alerts get published immediately (with cooldown)
                    if threat == "High":
                        alert_lock = f"alert_lock:{aadhar}:{client_id}"
                        if not cache_str.get(alert_lock):
                            cache.publish("security_alerts", json.dumps(msg_data))
                            cache_str.set(alert_lock, "1", ex=int(ALERT_COOLDOWN_S))
                    else:
                        # Normal intelligence updates
                        intel_lock = f"intel_lock:{aadhar}:{client_id}"
                        if not cache_str.get(intel_lock):
                            cache.publish("security_alerts", json.dumps(msg_data))
                            cache_str.set(intel_lock, "1", ex=10) # 10s cooldown for regular intel

            res_key = f"stream:{client_id}:results"
            cache.rpush(res_key, serde.pack(packet))
            cache.ltrim(res_key, -5, -1) # Keep only 5 recent results
            
            if packet.get('frame_count', 0) % 50 == 0:
                print(f"SINK: Finished processing {client_id} | Faces: {len(recognition)}")
                
        except Exception as e:
            print(f"ERROR in Sink Service: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)

if __name__ == "__main__":
    try:
        run_sink_service()
    except KeyboardInterrupt:
        print("\nStopping Sink Service...")
