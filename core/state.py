import redis
from redis import ConnectionPool
from collections import deque
from PyQt6.QtCore import QObject, pyqtSignal

class GlobalSignals(QObject):
    faiss_updated = pyqtSignal()

global_signals = GlobalSignals()

# ---------------------------------------------------------------------------
# Redis Connection Configuration
# Two pools are used:
#   1. `cache`     – decode_responses=False (stores raw binary JPEG frames)
#   2. `cache_str` – decode_responses=True  (string keys: cooldown, locks, JSON)
#      Using separate clients avoids .decode('utf-8') call-sites everywhere.
# ---------------------------------------------------------------------------
_binary_pool = ConnectionPool(
    host='localhost', port=6379, db=0,
    max_connections=20,
    decode_responses=False
)
_string_pool = ConnectionPool(
    host='localhost', port=6379, db=0,
    max_connections=20,
    decode_responses=True
)

# Keyspace Definitions:
# "stream:{client_id}:frame" -> Binary JPEG data (String with TTL)  [binary pool]
# "registry:active_streams"  -> Set of client IDs                   [binary pool]
# "signal:new_stream"        -> List for Pub/Sub-like notifications  [binary pool]
# "cache:face:{hash}"        -> Identity JSON string (TTL 10s)       [string pool]
# "cooldown:log:{a}:{c}"     -> Cooldown flag (TTL 120s)             [string pool]
# "cache:cam_loc:{client_id}"-> Camera location JSON (TTL 3600s)     [string pool]

cache = redis.Redis(connection_pool=_binary_pool)
cache_str = redis.Redis(connection_pool=_string_pool)

# Helper to verify connectivity
try:
    cache.ping()
    print("Redis: Connected successfully.")
except Exception as e:
    print(f"Redis: Connection failed: {e}")
    # Fallback/Safety would go here if needed, but Redis is required for this phase.

# We keep this for UI transition logic to avoid breaking current dashboard polling immediately
new_stream_signals = deque()
