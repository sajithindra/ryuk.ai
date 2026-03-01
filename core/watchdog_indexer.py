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
import base64
import json
from datetime import datetime, timedelta

from config import (
    DATA_DIR, IDENTITIES_PKL, FAISS_THRESHOLD,
    LOG_COOLDOWN_S, CAM_LOC_TTL_S,
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
        self._faiss_index = None
        self._faiss_mapping: list[dict] = []
        self._db = None
        self._profiles_col  = None
        self._cameras_col   = None
        self._activity_col  = None
        self._connect_db()
        self._migrate_pickle()
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_index(self):
        """Rebuilds the in-memory FAISS index from MongoDB."""
        if self._db is None:
            print("FAISS Error: MongoDB unreachable. Cannot rebuild index.")
            return

        try:
            identities = list(self._profiles_col.find({}))
        except Exception as e:
            print(f"FAISS: DB query error: {e}")
            return

        if not identities:
            self._faiss_index   = None
            self._faiss_mapping = []
            return

        embeddings, mapping = [], []
        for doc in identities:
            emb = np.frombuffer(doc["embedding"], dtype="float32")
            mapping.append({
                "aadhar":      doc.get("aadhar", "Unknown"),
                "name":        doc.get("name", "Unknown"),
                "threat_level": doc.get("threat_level", "Low"),
                "phone":       doc.get("phone", "N/A"),
                "address":     doc.get("address", "N/A"),
                "photo_thumb": doc.get("photo_thumb", ""),
            })
            embeddings.append(emb)

        mat = np.array(embeddings, dtype="float32")
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        mat /= norms

        idx = faiss.IndexFlatIP(512)
        idx.add(mat)

        self._faiss_index   = idx
        self._faiss_mapping = mapping
        print(f"FAISS: Loaded {len(identities)} identities.")

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
            {"$set": {
                "name": name, "threat_level": threat_level,
                "phone": phone, "address": address,
                "embedding": embedding.tobytes(),
                "photo_thumb": thumb_b64,
            }},
            upsert=True,
        )
        self.update_index()
        print(f"FAISS: Enrolled {name}.")

    def recognize_face(self, embedding: np.ndarray,
                       threshold: float = FAISS_THRESHOLD) -> dict | None:
        """Query FAISS index. Returns metadata dict or None."""
        if self._faiss_index is None or self._faiss_index.ntotal == 0:
            return None
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        query = np.array([embedding], dtype="float32")
        sims, idxs = self._faiss_index.search(query, k=1)
        if sims[0][0] > threshold and idxs[0][0] != -1:
            return self._faiss_mapping[idxs[0][0]]
        return None

    def log_activity(self, aadhar: str, client_id: str):
        """Record a timestamped detection, gated by a Redis cooldown key."""
        if self._activity_col is None:
            return
        cooldown_key = f"cooldown:log:{aadhar}:{client_id}"
        if cache_str.exists(cooldown_key):
            return

        loc_key   = f"cache:cam_loc:{client_id}"
        cached    = cache_str.get(loc_key)
        if cached:
            locations = json.loads(cached)
        else:
            cam       = self._cameras_col.find_one({"client_id": client_id})
            locations = cam.get("locations", ["Unknown", "Unknown"]) if cam else ["Unknown", "Unknown"]
            cache_str.setex(loc_key, int(CAM_LOC_TTL_S), json.dumps(locations))

        try:
            self._activity_col.insert_one({
                "aadhar":    aadhar,
                "client_id": client_id,
                "locations": locations,
                "timestamp": datetime.now(),
                "date_str":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            cache_str.setex(cooldown_key, int(LOG_COOLDOWN_S), "1")
            print(f"Watchdog: Logged {aadhar} @ {client_id} {locations}")
        except Exception as e:
            print(f"Watchdog: Log failed — {e}")

    def get_all_profiles(self) -> list[dict]:
        if self._db is None:
            return []
        try:
            return list(self._profiles_col.find({}))
        except Exception:
            return []

    def delete_profile(self, aadhar: str):
        if self._db is None:
            return
        self._profiles_col.delete_one({"aadhar": aadhar})
        self.update_index()
        print(f"MongoDB: Deleted {aadhar}")

    def update_profile(self, aadhar: str, data: dict):
        if self._db is None:
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
            return list(
                self._activity_col.find(query).sort("timestamp", -1).limit(limit)
            )
        except Exception as e:
            print(f"Watchdog: Report failed — {e}")
            return []

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
def enroll_face(*a, **kw):          _indexer.enroll_face(*a, **kw)
def recognize_face(emb, threshold=FAISS_THRESHOLD):
    return _indexer.recognize_face(emb, threshold)
def log_activity(aadhar, client_id): _indexer.log_activity(aadhar, client_id)
def get_all_profiles():             return _indexer.get_all_profiles()
def delete_profile(aadhar):         _indexer.delete_profile(aadhar)
def update_profile(aadhar, data):   _indexer.update_profile(aadhar, data)
def get_activity_report(aadhar, limit=50, days_ago=None):
    return _indexer.get_activity_report(aadhar, limit, days_ago)
def register_camera_metadata(cid, locs): _indexer.register_camera_metadata(cid, locs)

# Legacy aliases kept for any direct attribute access
faiss_index   = property(lambda _: _indexer._faiss_index)
faiss_mapping = property(lambda _: _indexer._faiss_mapping)
