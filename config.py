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

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE  = os.path.join(BASE_DIR, "main.log")
DATA_DIR       = os.path.join(BASE_DIR, "data")
MODELS_DIR     = os.path.join(DATA_DIR, "models")
TRT_CACHE_DIR  = os.path.join(DATA_DIR, "trt_cache")
IDENTITIES_PKL = os.path.join(DATA_DIR, "identities.pkl")



# ---------------------------------------------------------------------------
# Face recognition
# ---------------------------------------------------------------------------
FAISS_THRESHOLD       = 0.40   # Base threshold for recognition
ADAPTIVE_THRESHOLD_ENABLED = True
ADAPTIVE_MIN_THRESHOLD = 0.35  # Never go below this (too sensitive)
ADAPTIVE_MAX_THRESHOLD = 0.60  # Never go above this (too conservative)
SCORE_HISTORY_SIZE     = 100   # Sliding window for distribution tracking

MAX_POSES_PER_ID      = 10     # Max reference embeddings per person
AUTO_AUGMENT_MIN_SIM  = 0.35   # Similarity > this + tilt = auto-add to profile
AUTO_AUGMENT_TILT_DEG = 15     # Yaw/Pitch/Roll > this = "tilted"
FACE_MAX_INACTIVE_S   = 3.0    # Remove unidentified face box after 3s without detection
FACE_PINNED_MAX_INACTIVE_S = 30.0 # Keep identified person track for 30s
FACE_TRACK_MAX_DIST   = 400    # Increased for fast movement and head twists
FACE_TRACK_HISTORY    = 5      # Max embedding history per tracked face

# GLOBAL AI PROCESSOR BATCHING
AI_BATCH_SIZE = 4            # Smaller batches for lower latency
AI_BATCH_TIMEOUT_MS = 5      # 5ms timeout balances throughput and latency

# Performance/Throttling
INPUT_FPS        = 30        # Expected camera input FPS
PROCESSING_FPS   = 25        # Target processing/display FPS (Smoothness)
FRAME_SKIP       = INPUT_FPS // PROCESSING_FPS

INFERENCE_THROTTLE = 1       # Process every Nth frame (Detect/Embed) relative to PROCESSING_FPS
MAX_INFERENCE_SIZE = 640     # Optimal for TensorRT/InsightFace

# Detection Throttling (for "Detect Once and Track")
DETECTION_INTERVAL = 5       # Run detector every N frames. Track in between.
TRACKING_ONLY_ENABLED = True  # Enable Kalman-based tracking prediction between detections

# DeepSORT Tracking
TRACKER_MAX_AGE = 300         # Sustained for 10s at 30fps
TRACKER_N_INIT  = 1          # Show face boxes immediately (1 frame to confirm)
TRACKER_MATCH_THRESHOLD = 0.7 # Cosine distance threshold for appearance matching
TRACKER_IOU_THRESHOLD   = 0.3 # IoU threshold for spatial matching



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
# RTSP & Video Processing
# ---------------------------------------------------------------------------
RTSP_TRANSPORT = "tcp"  # Use TCP for more reliable delivery and lower jitter
USE_FFMPEG_CUDA = True  # Set to True to force GPU decoding via FFmpeg sub-process (NVDEC)
USE_GSTREAMER = True    # Set to True to use GStreamer for low-latency RTSP decoding
RTSP_LOW_LATENCY_FLAGS = [
    "fflags+nobuffer",
    "fflags+igndts",
    "flags+low_delay",
    "strict+experimental",
    "rtsp_transport+tcp",
]
VIDEO_JPEG_QUALITY = 85
VIDEO_DRAW_THICKNESS_SCALE = 400
VIDEO_FONT_SCALE_BASE = 1600.0
RTSP_URL_TEMPLATE = os.getenv("RTSP_URL_TEMPLATE", "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel=1&subtype=1")

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
WINDOW_WIDTH  = 1400
WINDOW_HEIGHT = 900
POLL_INTERVAL_MS   = 100
ALERT_INTERVAL_MS  = 100
CLEANUP_INTERVAL_MS = 1000
HEALTH_INTERVAL_MS = 3000
INTEL_CLEANUP_S    = 5.0   # Remove intel card if person unseen for N seconds
INTEL_PANEL_WIDTH  = 320
