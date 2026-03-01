"""
config.py — Central configuration for Ryuk AI.
All magic strings, URIs, thresholds and paths live here.
Import this module instead of repeating literals across files.
"""
import os

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB   = 0
REDIS_MAX_CONNECTIONS = 20

MONGO_URI  = "mongodb://localhost:27017"
DB_NAME    = "ryuk_ai"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
DATA_DIR       = os.path.join(BASE_DIR, "data")
TRT_CACHE_DIR  = os.path.join(DATA_DIR, "trt_cache")
IDENTITIES_PKL = os.path.join(DATA_DIR, "identities.pkl")

# ---------------------------------------------------------------------------
# Face recognition
# ---------------------------------------------------------------------------
FAISS_THRESHOLD       = 0.48   # Balanced for lighting/pose (0.60 was too strict)
MAX_POSES_PER_ID      = 10     # Max reference embeddings per person
AUTO_AUGMENT_MIN_SIM  = 0.35   # Similarity > this + tilt = auto-add to profile
AUTO_AUGMENT_TILT_DEG = 15     # Yaw/Pitch/Roll > this = "tilted"
INFERENCE_THROTTLE    = 4      # Run heavy AI every Nth frame
FACE_MAX_INACTIVE_S   = 2.0    # Seconds before a stale track is pruned
FACE_TRACK_MAX_DIST   = 150    # Max centroid distance for track matching
FACE_TRACK_HISTORY    = 5      # Max embedding history per tracked face
MAX_INFERENCE_SIZE    = 480    # Max frame dimension for inference downscale

# ---------------------------------------------------------------------------
# Redis TTLs & cooldowns
# ---------------------------------------------------------------------------
FACE_CACHE_TTL_S  = 15    # Cache a recognised identity for N seconds
ALERT_COOLDOWN_S  = 10    # Don't re-publish an alert for same person/cam
LOG_COOLDOWN_S    = 120   # Don't re-log activity for same person/cam
CAM_LOC_TTL_S     = 3600  # Cache camera location metadata for N seconds

# ---------------------------------------------------------------------------
# Streaming server
# ---------------------------------------------------------------------------
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
WINDOW_WIDTH  = 1400
WINDOW_HEIGHT = 900
POLL_INTERVAL_MS   = 500
ALERT_INTERVAL_MS  = 500
CLEANUP_INTERVAL_MS = 1000
HEALTH_INTERVAL_MS = 3000
INTEL_CLEANUP_S    = 5.0   # Remove intel card if person unseen for N seconds
INTEL_PANEL_WIDTH  = 320
