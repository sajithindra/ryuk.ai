import redis
from collections import deque
from PyQt6.QtCore import QObject, pyqtSignal

class GlobalSignals(QObject):
    faiss_updated = pyqtSignal()

global_signals = GlobalSignals()

# Initialize Redis client (standard local connection)
cache = redis.Redis(host='localhost', port=6379, db=0)

# Keyspace Definitions:
# "stream:{client_id}:frame" -> Binary JPEG data (String with TTL)
# "registry:active_streams"  -> Set of client IDs
# "signal:new_stream"        -> List for Pub/Sub-like notifications
# "cache:face:{hash}"        -> Identity JSON string (TTL 10s)

# Helper to verify connectivity
try:
    cache.ping()
    print("Redis: Connected successfully.")
except Exception as e:
    print(f"Redis: Connection failed: {e}")
    # Fallback/Safety would go here if needed, but Redis is required for this phase.

# We keep this for UI transition logic to avoid breaking current dashboard polling immediately
new_stream_signals = deque()
