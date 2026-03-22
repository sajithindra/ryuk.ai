import redis
import pickle
import numpy as np
import cv2
import time
import core.serialization as serde

r = redis.Redis(host='localhost', port=6379, db=0)
frame = np.zeros((640, 640, 3), dtype=np.uint8)
packet = {
    'frame': frame,
    'client_id': 'test_client',
    'frame_count': 0,
    'timestamp': time.time()
}
r.rpush('ryuk:ingest', serde.pack(packet))
print("Pushed dummy frame to ryuk:ingest")
