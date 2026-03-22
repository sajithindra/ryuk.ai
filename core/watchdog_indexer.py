"""
core/watchdog_indexer.py

Encapsulates all identity-registry operations in WatchdogIndexer.
Previously these were bare module-level functions operating on
global mutable state (faiss_index, faiss_mapping).

Module-level shims at the bottom keep every existing call-site working
with zero changes elsewhere (dashboard.py, video_worker.py, etc.).
"""
import os
import cv2
import pickle
import numpy as np
import faiss
import threading
import base64
import json
from datetime import datetime, timedelta
from collections import deque

from config import (
    DATA_DIR, IDENTITIES_PKL, FAISS_THRESHOLD,
    LOG_COOLDOWN_S, CAM_LOC_TTL_S, MAX_POSES_PER_ID,
    AUTO_AUGMENT_MIN_SIM, AUTO_AUGMENT_TILT_DEG,
    ADAPTIVE_THRESHOLD_ENABLED, ADAPTIVE_MIN_THRESHOLD,
    ADAPTIVE_MAX_THRESHOLD, SCORE_HISTORY_SIZE
)
from core.ai_processor import face_app
from core.database import get_sync_db
from core.state import cache, cache_str


class WatchdogIndexer:
    """
    Manages the face-recognition pipeline:
      - FAISS in-memory index (CPU) rebuilt from MongoDB
      - Face enrolment with thumbnail generation
      - Activity logging with Redis-based cooldown
      - Profile CRUD operations
    """

    def __init__(self):
        self._faiss_res = faiss.StandardGpuResources()
        self._faiss_index = None
        self._faiss_mapping: list[dict] = []
        self._lock = threading.Lock()
        self._db = None
        self._profiles_col  = None
        self._cameras_col   = None
        self._activity_col  = None
        self._connect_db()
        self._migrate_pickle()
        self._migrate_embeddings_schema()
        
        # Adaptive Thresholding Distribution Tracking
        self._unknown_scores = deque(maxlen=SCORE_HISTORY_SIZE)
        self._known_scores   = deque(maxlen=SCORE_HISTORY_SIZE)

        self.update_index()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect_db(self):
        """Obtain a synchronous MongoDB handle."""
        db = get_sync_db()
        if db is not None:
            self._db             = db
            self._profiles_col   = db["profiles"]
            self._cameras_col    = db["cameras"]
            self._activity_col   = db["activity_logs"]

    def _migrate_pickle(self):
        """One-time migration of legacy identities.pkl → MongoDB."""
        if not os.path.exists(IDENTITIES_PKL):
            return
        print("MongoDB: Found legacy identities.pkl. Migrating…")
        try:
            with open(IDENTITIES_PKL, "rb") as f:
                identities = pickle.load(f)
            for item in identities:
                if len(item) == 2:
                    emb, aadhar = item; name, threat = "Unknown", "Low"
                elif len(item) == 3:
                    emb, aadhar, name = item; threat = "Low"
                else:
                    emb, aadhar, name, threat = item
                self._profiles_col.update_one(
                    {"aadhar": aadhar},
                    {"$set": {"name": name, "threat_level": threat,
                              "embedding": emb.tobytes()}},
                    upsert=True,
                )
            os.rename(IDENTITIES_PKL, IDENTITIES_PKL + ".bak")
            print(f"MongoDB: Migration complete. {len(identities)} profiles moved.")
        except Exception as e:
            print(f"MongoDB: Migration error: {e}")

    def _migrate_embeddings_schema(self):
        """Convert legacy single 'embedding' field to 'embeddings' list in MongoDB."""
        if self._db is None:
            return
        
        # Find all docs that have 'embedding' but NOT 'embeddings'
        legacy_docs = list(self._profiles_col.find({
            "embedding": {"$exists": True},
            "embeddings": {"$exists": False}
        }))
        
        if not legacy_docs:
            return
            
        print(f"MongoDB: Found {len(legacy_docs)} legacy profiles. Converting to list schema…")
        for doc in legacy_docs:
            self._profiles_col.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {"embeddings": [doc["embedding"]]},
                    "$unset": {"embedding": ""}
                }
            )
        print("MongoDB: Schema migration complete.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_index(self):
        """Rebuilds the in-memory FAISS index from MongoDB."""
        if self._db is None or self._profiles_col is None:
            print("FAISS Error: MongoDB unreachable. Cannot rebuild index.")
            return

        try:
            # Optimize: Only pull necessary fields for the index mapping
            projection = {
                "aadhar": 1, "name": 1, "threat_level": 1, 
                "phone": 1, "address": 1, "photo_thumb": 1, 
                "embeddings": 1
            }
            identities = list(self._profiles_col.find({}, projection))
        except Exception as e:
            print(f"FAISS: DB query error: {e}")
            return

        if not identities:
            with self._lock:
                self._faiss_index   = None
                self._faiss_mapping = []
            return

        embeddings, mapping = [], []
        for doc in identities:
            # Handle multi-embedding support
            doc_embs = doc.get("embeddings", [])
            person_meta = {
                "aadhar":      doc.get("aadhar", "Unknown"),
                "name":        doc.get("name", "Unknown"),
                "threat_level": doc.get("threat_level", "Low"),
                "phone":       doc.get("phone", "N/A"),
                "address":     doc.get("address", "N/A"),
                "photo_thumb": doc.get("photo_thumb", ""),
            }
            
            for emb_bytes in doc_embs:
                emb = np.frombuffer(emb_bytes, dtype="float32")
                embeddings.append(emb)
                mapping.append(person_meta)

        if not embeddings:
            with self._lock:
                self._faiss_index = None
                self._faiss_mapping = []
            return

        mat = np.array(embeddings, dtype="float32")
        # Ensure contiguous memory layout for FAISS
        mat = np.ascontiguousarray(mat)
        
        # Safety normalization (in case some DB entries are legacy/unnormalized)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        mat /= norms

        # HNSW Index for production querying
        # Use inner product (requires normalized vectors)
        cpu_idx = faiss.IndexHNSWFlat(512, 32, faiss.METRIC_INNER_PRODUCT)
        cpu_idx.add(mat)

        # HNSWFlat is highly optimized for CPU but not directly implemented on GPU.
        # It provides ultra-fast search times even on CPU for 512D vectors.
        # Note: faiss.index_cpu_to_gpu does not support cloning IndexHNSWFlat to GPU.
        
        # Atomic Swap (Zero-Downtime)
        with self._lock:
            self._faiss_index = cpu_idx
            self._faiss_mapping = mapping
        
        # Signal change via Redis
        try:
            cache.set("ryuk:index:version", str(time.time()))
        except Exception:
            pass
            
        print(f"FAISS: (Shadow Index Synced) Loaded {len(embeddings)} vectors for {len(identities)} identities.")

    def rebuild_index_background(self):
        """Launches update_index in a daemon thread."""
        thread = threading.Thread(target=self.update_index, daemon=True)
        thread.start()
        return thread

    def enroll_face(self, image_path: str, aadhar: str, name: str,
                    threat_level: str = "Low", phone: str = "", address: str = ""):
        """Extract embedding from image and save full profile to MongoDB."""
        if not os.path.exists(image_path):
            raise ValueError(f"Image not found: {image_path}")

        frame = cv2.imread(image_path)
        if frame is None:
            raise ValueError("Could not decode image.")

        faces = face_app.get(frame)
        if not faces:
            raise ValueError("No faces detected.")
        if len(faces) > 1:
            raise ValueError("Multiple faces in enrolment image.")

        face      = faces[0]
        embedding = face.embedding

        # Generate thumbnail
        thumb_b64 = ""
        try:
            bbox     = face.bbox.astype(int)
            h, w, _  = frame.shape
            mx = int((bbox[2] - bbox[0]) * 0.2)
            my = int((bbox[3] - bbox[1]) * 0.2)
            y1, y2   = max(0, bbox[1] - my), min(h, bbox[3] + my)
            x1, x2   = max(0, bbox[0] - mx), min(w, bbox[2] + mx)
            face_img = cv2.resize(frame[y1:y2, x1:x2], (160, 160))
            _, buf   = cv2.imencode(".jpg", face_img,
                                    [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            thumb_b64 = base64.b64encode(buf).decode("utf-8")
        except Exception as e:
            print(f"Watchdog: Thumbnail failed — {e}")

        self._profiles_col.update_one(
            {"aadhar": aadhar},
            {
                "$set": {
                    "name": name, "threat_level": threat_level,
                    "phone": phone, "address": address,
                    "photo_thumb": thumb_b64,
                },
                "$push": {
                    "embeddings": {
                        "$each": [embedding.astype(np.float32).tobytes()],
                        "$slice": -MAX_POSES_PER_ID  # Keep last N poses
                    }
                }
            },
            upsert=True,
        )
        
        # Incremental Index Update
        # embedding is already normalized from face_app.get(frame)
        norm_emb = np.ascontiguousarray(embedding.astype(np.float32))
        # Update FAISS index
        with self._lock:
            if self._faiss_index is None:
                self.update_index()
            else:
                self._faiss_index.add(np.array([norm_emb], dtype="float32"))
                self._faiss_mapping.append({
                    "aadhar": aadhar, "name": name, "threat_level": threat_level,
                    "phone": phone, "address": address, "photo_thumb": thumb_b64
                })
        
        print(f"FAISS: Enrolled {name} (Incremental update).")


    def recognize_face(self, embedding: np.ndarray,
                       threshold: float = FAISS_THRESHOLD, **kwargs) -> dict | None:
        """Query FAISS GPU Index directly."""
        # 1. Slow Path: FAISS GPU Index
        # Atomic snapshot of index/mapping for search consistency
        with self._lock:
            index = self._faiss_index
            mapping = self._faiss_mapping

        if index is None or index.ntotal == 0:
            return None
        
        # Extract quality metric from embedding norm if not provided
        # NOTE: embedding is already normalized (L2=1.0) and float32 from GlobalAIProcessor
        query = np.ascontiguousarray(embedding.reshape(1, -1).astype(np.float32))
        sims, idxs = index.search(query, k=1)
        score = float(sims[0][0])
        
        # Calculate Adaptive Threshold
        context = kwargs.get("context", {}).copy()
        if "norm" not in context:
            # Fallback if norm missing, though SearchService should provide it
            context["norm"] = 30.0 
            
        current_threshold = self._calculate_adaptive_threshold(context) if threshold == FAISS_THRESHOLD else threshold
        
        # BIO-LOG: Distribution tracking
        result = None
        if score > current_threshold and idxs[0][0] != -1:
            result = mapping[idxs[0][0]].copy()
            result['score'] = score
            self._known_scores.append(score)
        elif idxs[0][0] != -1:
            result = {'score': score}
            # Only track as noise if it's a realistic face match (score > 0.1)
            if score > 0.1:
                self._unknown_scores.append(score)

        # Logging for system observability
        if score > 0.2:
            print(f"BIO-LOG: Score: {score:.3f} | Threshold: {current_threshold:.3f} | {'MATCH' if result and result.get('aadhar') else 'REJECT'}")

        return result

        return result

    def _calculate_adaptive_threshold(self, context: dict | None = None) -> float:
        """
        Dynamically adjust the threshold based on environmental factors 
        and historical score distribution.
        """
        base_threshold = FAISS_THRESHOLD
        
        if not ADAPTIVE_THRESHOLD_ENABLED:
            return base_threshold

        # 1. Statistical Noise Floor (moving average of recent unknown scores)
        # If the environment is noisy, we push the threshold higher.
        if len(self._unknown_scores) > 10:
             noise_floor = np.mean(self._unknown_scores) + (1.5 * np.std(self._unknown_scores))
             base_threshold = max(base_threshold, noise_floor)

        if not context:
            return base_threshold

        # 2. Lighting Penalty (U-shaped penalty)
        # Optimal brightness is ~0.5. Very dark (<0.2) or very bright (>0.8) is penalized.
        brightness = context.get("brightness", 0.5)
        lighting_penalty = 0.0
        if brightness < 0.35:
            lighting_penalty = (0.35 - brightness) * 0.4  # Penalty for low light
        elif brightness > 0.75:
             lighting_penalty = (brightness - 0.75) * 0.3  # Penalty for over-exposure
        
        # 3. Embedding Quality (InsightFace 'norm')
        # Typical norms for good detections are 25-35. Below 18 is risky.
        norm = context.get("norm", 30.0)
        quality_penalty = 0.0
        if norm < 20.0:
            quality_penalty = (20.0 - norm) * 0.01  # Penalty for low resolution/quality
            
        # 4. Pose Penalty (Yaw/Pitch/Roll)
        # Frontal faces are (0,0,0). Angles > 25 degrees are penalized.
        pose = context.get("pose")
        if pose is None:
            pose = [0, 0, 0]
            
        pose_penalty = sum(max(0, abs(angle) - 25) for angle in pose) * 0.001 
        
        adaptive_threshold = base_threshold + lighting_penalty + quality_penalty + pose_penalty
        
        return float(np.clip(adaptive_threshold, ADAPTIVE_MIN_THRESHOLD, ADAPTIVE_MAX_THRESHOLD))

    def log_activity(self, aadhar: str, client_id: str):
        """Record a timestamped detection, gated by a Redis cooldown key."""
        if self._activity_col is None:
            return
        cooldown_key = f"cooldown:log:{aadhar}:{client_id}"
        if cache_str.exists(cooldown_key):
            return

        loc_key   = f"cache:cam_loc:{client_id}"
        dev_key   = f"cache:cam_dev:{client_id}"
        
        cached_loc = cache_str.get(loc_key)
        cached_dev = cache_str.get(dev_key)
        
        if cached_loc and cached_dev:
            location = cached_loc
            device_info = json.loads(cached_dev)
        else:
            # Use projection to minimize data transfer
            projection = {"locations": 1, "device_info": 1}
            cam = self._cameras_col.find_one({"client_id": client_id}, projection)
            
            # Locations
            loc_list = cam.get("locations", ["Main Terminal"]) if cam else ["Main Terminal"]
            location = loc_list[0] if loc_list else "Main Terminal"
            # Device Info
            device_info = cam.get("device_info", {}) if cam else {}
            
            # Pipeline metadata caching
            pipe = cache_str.pipeline()
            pipe.setex(loc_key, int(CAM_LOC_TTL_S), location)
            pipe.setex(dev_key, int(CAM_LOC_TTL_S), json.dumps(device_info))
            pipe.execute()

        try:
            self._activity_col.insert_one({
                "aadhar":      aadhar,
                "client_id":   client_id,
                "location":    location,
                "device_info": device_info,
                "timestamp":   datetime.now(),
                "date_str":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            cache_str.setex(cooldown_key, int(LOG_COOLDOWN_S), "1")
            print(f"Watchdog: Logged {aadhar} @ {location} ({device_info.get('device_name','?')})")
        except Exception as e:
            print(f"Watchdog: Log failed — {e}")

    def get_all_profiles(self) -> list[dict]:
        if self._profiles_col is None:
            return []
        try:
            projection = {"embeddings": 0} # Exclude heavy embeddings for general listing
            return list(self._profiles_col.find({}, projection))
        except Exception:
            return []

    def delete_profile(self, aadhar: str):
        if self._profiles_col is None:
            return
        self._profiles_col.delete_one({"aadhar": aadhar})
        self.update_index()
        print(f"MongoDB: Deleted {aadhar}")

    def update_profile(self, aadhar: str, data: dict):
        if self._profiles_col is None:
            return
        self._profiles_col.update_one({"aadhar": aadhar}, {"$set": data})
        self.update_index()
        print(f"MongoDB: Updated {aadhar}")

    def get_activity_report(self, aadhar: str, limit: int = 50,
                            days_ago: int | None = None) -> list[dict]:
        if self._activity_col is None:
            return []
        try:
            query: dict = {"aadhar": aadhar}
            if days_ago is not None:
                query["timestamp"] = {"$gte": datetime.now() - timedelta(days=days_ago)}
            projection = {"_id": 0} # Example projection
            return list(
                self._activity_col.find(query, projection).sort("timestamp", -1).limit(limit)
            )
        except Exception as e:
            print(f"Watchdog: Report failed — {e}")
            return []

    def augment_identity(self, aadhar: str, embedding: np.ndarray):
        """Add a new embedding (pose) to an existing profile in MongoDB."""
        if self._profiles_col is None or not aadhar:
            return
            
        self._profiles_col.update_one(
            {"aadhar": aadhar},
            {
                "$push": {
                    "embeddings": {
                        "$each": [embedding.astype(np.float32).tobytes()],
                        "$slice": -MAX_POSES_PER_ID
                    }
                }
            }
        )
        
        # Incremental Index Update
        # embedding is already normalized from face_app.get()
        norm_emb = np.ascontiguousarray(embedding.astype(np.float32))
        # Update FAISS index
        with self._lock:
            if self._faiss_index is None:
                self.update_index()
            else:
                self._faiss_index.add(np.array([norm_emb], dtype="float32"))
                # We need to find the meta for this aadhar to keep mapping consistent
                meta = next((m for m in self._faiss_mapping if m["aadhar"] == aadhar), {"aadhar": aadhar})
                self._faiss_mapping.append(meta)
            
        print(f"Watchdog: Augmented {aadhar} with new pose (Incremental).")

    def delete_camera(self, client_id: str):
        if self._cameras_col is None:
            return
        self._cameras_col.delete_one({"client_id": client_id})
        # Clean up Redis cache for this camera
        loc_key   = f"cache:cam_loc:{client_id}"
        dev_key   = f"cache:cam_dev:{client_id}"
        cache_str.delete(loc_key, dev_key)
        print(f"MongoDB: Deleted Camera {client_id}")

    def register_camera_metadata(self, client_id: str, locations: list):
        if self._cameras_col is None:
            return
        self._cameras_col.update_one(
            {"client_id": client_id},
            {"$set": {"locations": locations[:2]}},
            upsert=True,
        )
        print(f"MongoDB: Camera {client_id} → {locations}")


# ---------------------------------------------------------------------------
# Module-level singleton + backward-compat shims
# Every existing caller (dashboard.py, video_worker.py, etc.) can continue
# using  `import core.watchdog_indexer as watchdog` + `watchdog.func()`
# without any changes.
# ---------------------------------------------------------------------------
_indexer = WatchdogIndexer()

def update_faiss_index():           _indexer.update_index()
def rebuild_index_background():     return _indexer.rebuild_index_background()
def enroll_face(*a, **kw):          _indexer.enroll_face(*a, **kw)
def recognize_face(emb, threshold=FAISS_THRESHOLD, **kwargs):
    return _indexer.recognize_face(emb, threshold, **kwargs)
def log_activity(aadhar, client_id): _indexer.log_activity(aadhar, client_id)
def get_all_profiles():             return _indexer.get_all_profiles()
def delete_profile(aadhar):         _indexer.delete_profile(aadhar)
def update_profile(aadhar, data):   _indexer.update_profile(aadhar, data)
def get_activity_report(aadhar, limit=50, days_ago=None):
    return _indexer.get_activity_report(aadhar, limit, days_ago)
def augment_identity(aadhar, emb): _indexer.augment_identity(aadhar, emb)
def delete_camera(cid):             _indexer.delete_camera(cid)
def register_camera_metadata(cid, locs): _indexer.register_camera_metadata(cid, locs)

# Legacy aliases kept for any direct attribute access
faiss_index   = property(lambda _: _indexer._faiss_index)
faiss_mapping = property(lambda _: _indexer._faiss_mapping)
