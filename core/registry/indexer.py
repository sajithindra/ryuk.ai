"""
core/registry/indexer.py
Encapsulates all identity-registry operations in WatchdogIndexer.
Optimized for modularity and performance.
"""
import os
import cv2
import base64
import json
import numpy as np
import faiss
import threading
import time
import pickle
from datetime import datetime, timedelta
from collections import deque
from core.logger import logger
from core.database import get_sync_db
from core.state import cache, cache_str
from config import (
    DATA_DIR, IDENTITIES_PKL, FAISS_THRESHOLD,
    LOG_COOLDOWN_S, CAM_LOC_TTL_S, MAX_POSES_PER_ID,
    ADAPTIVE_THRESHOLD_ENABLED, ADAPTIVE_MIN_THRESHOLD,
    ADAPTIVE_MAX_THRESHOLD, SCORE_HISTORY_SIZE
)

class WatchdogIndexer:
    """
    Manages the face-recognition pipeline:
      - FAISS in-memory index built from MongoDB
      - Face enrolment with thumbnail generation
      - Activity logging with Redis-based cooldown
      - Profile CRUD operations
    """

    def __init__(self):
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
        self._cached_noise_floor = FAISS_THRESHOLD
        self._last_stats_update  = 0

        self.update_index()

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
        if not os.path.exists(IDENTITIES_PKL): return
        logger.info("[MIGRATION] Found legacy identities.pkl. Migrating…")
        try:
            with open(IDENTITIES_PKL, "rb") as f:
                identities = pickle.load(f)
            for item in identities:
                if len(item) == 2: emb, aadhar = item; name, threat = "Unknown", "Low"
                elif len(item) == 3: emb, aadhar, name = item; threat = "Low"
                else: emb, aadhar, name, threat = item
                self._profiles_col.update_one(
                    {"aadhar": aadhar},
                    {"$set": {"name": name, "threat_level": threat, "embedding": emb.tobytes()}},
                    upsert=True,
                )
            os.rename(IDENTITIES_PKL, IDENTITIES_PKL + ".bak")
            logger.info(f"[MIGRATION] Complete. {len(identities)} profiles moved.")
        except Exception as e:
            logger.error(f"[MIGRATION] Error: {e}")

    def _migrate_embeddings_schema(self):
        """Convert legacy single 'embedding' field to 'embeddings' list in MongoDB."""
        if self._db is None: return
        legacy_docs = list(self._profiles_col.find({"embedding": {"$exists": True}, "embeddings": {"$exists": False}}))
        if not legacy_docs: return
        logger.info(f"[MIGRATION] Found {len(legacy_docs)} legacy profiles. Converting to list schema…")
        for doc in legacy_docs:
            self._profiles_col.update_one(
                {"_id": doc["_id"]},
                {"$set": {"embeddings": [doc["embedding"]]}, "$unset": {"embedding": ""}}
            )

    def update_index(self):
        """Rebuilds the in-memory FAISS index from MongoDB."""
        if self._db is None or self._profiles_col is None:
            logger.error("FAISS Error: MongoDB unreachable.")
            return

        try:
            projection = {"aadhar": 1, "name": 1, "threat_level": 1, "phone": 1, "address": 1, "photo_thumb": 1, "embeddings": 1}
            identities = list(self._profiles_col.find({}, projection))
        except Exception as e:
            logger.error(f"FAISS: DB query error: {e}")
            return

        if not identities:
            with self._lock:
                self._faiss_index, self._faiss_mapping = None, []
            return

        embeddings, mapping = [], []
        for doc in identities:
            doc_embs = doc.get("embeddings", [])
            person_meta = {
                "aadhar": doc.get("aadhar", "Unknown"), "name": doc.get("name", "Unknown"),
                "threat_level": doc.get("threat_level", "Low"), "phone": doc.get("phone", "N/A"),
                "address": doc.get("address", "N/A"), "photo_thumb": doc.get("photo_thumb", ""),
            }
            for emb_bytes in doc_embs:
                embeddings.append(np.frombuffer(emb_bytes, dtype="float32"))
                mapping.append(person_meta)

        if not embeddings:
            with self._lock:
                self._faiss_index, self._faiss_mapping = None, []
            return

        mat = np.ascontiguousarray(np.array(embeddings, dtype="float32"))
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        mat /= norms

        cpu_idx = faiss.IndexHNSWFlat(512, 32, faiss.METRIC_INNER_PRODUCT)
        cpu_idx.add(mat)

        with self._lock:
            self._faiss_index, self._faiss_mapping = cpu_idx, mapping
        
        try: cache.set("ryuk:index:version", str(time.time()))
        except Exception: pass
        logger.info(f"FAISS: Loaded {len(embeddings)} vectors for {len(identities)} identities.")

    def enroll_face(self, image_source: str | bytes, aadhar: str = None, name: str = None,
                    threat_level: str = "Low", phone: str = "", address: str = "", 
                    metadata: dict = None):
        from core.ai_processor import get_ai_processor
        ai = get_ai_processor()
        
        # 1. Handle Metadata Dict if provided (for NiceGUI)
        if metadata:
            aadhar = metadata.get('aadhar', aadhar)
            name = metadata.get('name', name)
            threat_level = metadata.get('threat_level', threat_level)
            phone = metadata.get('phone', phone)
            address = metadata.get('address', address)

        # 2. Decode Image (File Path or Bytes)
        if isinstance(image_source, bytes):
            arr = np.frombuffer(image_source, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None: raise ValueError("Could not decode image bytes.")
        else:
            if not os.path.exists(image_source): raise ValueError(f"Image not found: {image_source}")
            frame = cv2.imread(image_source)
            if frame is None: raise ValueError("Could not decode image file.")

        # 3. Process with High Priority (Always skip frame-dropping logic)
        result = ai.get(frame, priority=True)
        faces = result.get("faces", [])
        if not faces: raise ValueError("No faces detected.")
        if len(faces) > 1: raise ValueError("Multiple faces in enrolment image.")

        face = faces[0]
        embedding = face.embedding
        thumb_b64 = ""
        try:
            bbox = face.bbox.astype(int)
            h, w = frame.shape[:2]
            mx, my = int((bbox[2] - bbox[0]) * 0.2), int((bbox[3] - bbox[1]) * 0.2)
            y1, y2, x1, x2 = max(0, bbox[1]-my), min(h, bbox[3]+my), max(0, bbox[0]-mx), min(w, bbox[2]+mx)
            face_img = cv2.resize(frame[y1:y2, x1:x2], (160, 160))
            _, buf = cv2.imencode(".jpg", face_img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            thumb_b64 = base64.b64encode(buf).decode("utf-8")
        except Exception as e: logger.error(f"Watchdog: Thumbnail failed — {e}")

        self._profiles_col.update_one(
            {"aadhar": aadhar},
            {
                "$set": {"name": name, "threat_level": threat_level, "phone": phone, "address": address, "photo_thumb": thumb_b64},
                "$push": {"embeddings": {"$each": [embedding.astype(np.float32).tobytes()], "$slice": -MAX_POSES_PER_ID}}
            },
            upsert=True,
        )
        
        norm_emb = np.ascontiguousarray(embedding.astype(np.float32))
        with self._lock:
            if self._faiss_index is None: self.update_index()
            else:
                self._faiss_index.add(np.array([norm_emb], dtype="float32"))
                self._faiss_mapping.append({"aadhar": aadhar, "name": name, "threat_level": threat_level, "phone": phone, "address": address, "photo_thumb": thumb_b64})
        logger.info(f"FAISS: Enrolled {name}.")

    def recognize_face(self, embedding: np.ndarray, threshold: float = FAISS_THRESHOLD, **kwargs) -> dict | None:
        with self._lock:
            index, mapping = self._faiss_index, self._faiss_mapping
        if index is None or index.ntotal == 0: return None
        
        query = np.ascontiguousarray(embedding.reshape(1, -1).astype(np.float32))
        sims, idxs = index.search(query, k=1)
        score = float(sims[0][0])
        
        current_threshold = self._calculate_adaptive_threshold(kwargs.get("context", {})) if threshold == FAISS_THRESHOLD else threshold
        
        result = None
        if score > current_threshold and idxs[0][0] != -1:
            result = mapping[idxs[0][0]].copy()
            result['score'] = score
            self._known_scores.append(score)
        elif idxs[0][0] != -1 and score > 0.1:
            self._unknown_scores.append(score)

        if score > 0.2:
            logger.debug(f"BIO-LOG: Score: {score:.3f} | Threshold: {current_threshold:.3f} | {'MATCH' if result and result.get('aadhar') else 'REJECT'}")
        return result

    def _calculate_adaptive_threshold(self, context: dict | None = None) -> float:
        base_threshold = FAISS_THRESHOLD
        if not ADAPTIVE_THRESHOLD_ENABLED: return base_threshold

        if len(self._unknown_scores) > 10:
            if self._last_stats_update % 10 == 0:
                noise_floor = np.mean(self._unknown_scores) + (1.5 * np.std(self._unknown_scores))
                self._cached_noise_floor = max(FAISS_THRESHOLD, noise_floor)
            self._last_stats_update += 1
            base_threshold = self._cached_noise_floor

        if not context: return base_threshold
        brightness = context.get("brightness", 0.5)
        lighting_penalty = max(0, 0.35 - brightness) * 0.4 if brightness < 0.35 else max(0, brightness - 0.75) * 0.3
        norm = context.get("norm", 30.0)
        quality_penalty = max(0, 20.0 - norm) * 0.01
        pose = context.get("pose", [0, 0, 0])
        pose_penalty = sum(max(0, abs(a) - 25) for a in pose) * 0.001 
        
        return float(np.clip(base_threshold + lighting_penalty + quality_penalty + pose_penalty, ADAPTIVE_MIN_THRESHOLD, ADAPTIVE_MAX_THRESHOLD))

    def log_activity(self, aadhar: str, client_id: str, action: str = "Unknown"):
        if self._activity_col is None: return
        cooldown_key = f"cooldown:log:{aadhar}:{client_id}"
        if cache_str.exists(cooldown_key): return

        loc_key, dev_key = f"cache:cam_loc:{client_id}", f"cache:cam_dev:{client_id}"
        cached_loc, cached_dev = cache_str.get(loc_key), cache_str.get(dev_key)
        
        if cached_loc and cached_dev:
            location, device_info = cached_loc, json.loads(cached_dev)
        else:
            cam = self._cameras_col.find_one({"client_id": client_id}, {"locations": 1, "device_info": 1})
            loc_list = cam.get("locations", []) if cam else []
            location = loc_list[0] if loc_list else cam.get("name") if cam else "Main Terminal"
            device_info = cam.get("device_info", {}) if cam else {}
            
            pipe = cache_str.pipeline()
            pipe.setex(loc_key, int(CAM_LOC_TTL_S), location)
            pipe.setex(dev_key, int(CAM_LOC_TTL_S), json.dumps(device_info))
            pipe.execute()

        try:
            self._activity_col.insert_one({"aadhar": aadhar, "client_id": client_id, "location": location, "device_info": device_info, "action": action, "timestamp": datetime.now(), "date_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            cache_str.setex(cooldown_key, int(LOG_COOLDOWN_S), "1")
            logger.info(f"Watchdog: Logged {aadhar} @ {location}")
        except Exception as e: logger.error(f"Watchdog: Log failed — {e}")

    def get_activity_report(self, aadhar: str, limit: int = 50,
                            days_ago: int | None = None) -> list[dict]:
        if self._activity_col is None: return []
        try:
            query: dict = {"aadhar": aadhar}
            if days_ago is not None:
                query["timestamp"] = {"$gte": datetime.now() - timedelta(days=days_ago)}
            return list(self._activity_col.find(query, {"_id": 0}).sort("timestamp", -1).limit(limit))
        except Exception as e:
            logger.error(f"Watchdog: Report failed — {e}")
            return []

    def delete_camera(self, client_id: str):
        if self._cameras_col is None: return
        self._cameras_col.delete_one({"client_id": client_id})
        cache_str.delete(f"cache:cam_loc:{client_id}", f"cache:cam_dev:{client_id}")
        logger.info(f"MongoDB: Deleted Camera {client_id}")

    def register_camera_metadata(self, client_id: str, locations: list, source: str = None):
        if self._cameras_col is None: return
        update_data = {"locations": locations[:2]}
        if source: update_data["source"] = source
        self._cameras_col.update_one({"client_id": client_id}, {"$set": update_data}, upsert=True)
        logger.info(f"MongoDB: Camera {client_id} → {locations} (Source: {source})")

    def get_all_profiles(self) -> list[dict]:
        if self._profiles_col is None: return []
        try: return list(self._profiles_col.find({}, {"embeddings": 0}))
        except Exception: return []

    def delete_profile(self, aadhar: str):
        if self._profiles_col is None: return
        self._profiles_col.delete_one({"aadhar": aadhar}); self.update_index()

    def update_profile(self, aadhar: str, data: dict):
        if self._profiles_col is None: return
        self._profiles_col.update_one({"aadhar": aadhar}, {"$set": data}); self.update_index()

    def augment_identity(self, aadhar: str, embedding: np.ndarray):
        if self._profiles_col is None or not aadhar or embedding is None: return
        self._profiles_col.update_one({"aadhar": aadhar}, {"$push": {"embeddings": {"$each": [embedding.astype(np.float32).tobytes()], "$slice": -MAX_POSES_PER_ID}}})
        norm_emb = np.ascontiguousarray(embedding.astype(np.float32))
        with self._lock:
            if self._faiss_index is None: self.update_index()
            else:
                self._faiss_index.add(np.array([norm_emb], dtype="float32"))
                meta = next((m for m in self._faiss_mapping if m["aadhar"] == aadhar), {"aadhar": aadhar})
                self._faiss_mapping.append(meta)
