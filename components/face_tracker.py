"""
components/face_tracker.py

FaceTracker manages face track lifecycle across video frames.
Previously this logic was embedded in VideoProcessor.run(),
making that method ~150 lines long.

Usage:
    tracker = FaceTracker()
    parsed  = tracker.update(faces_from_insightface, inf_scale)
    tracker.prune_stale()
    avg_emb = tracker.get_avg_embedding(track_id)
    tracker.clear()
"""
import time
import numpy as np
from collections import deque
from config import (
    FACE_TRACK_MAX_DIST,
    FACE_TRACK_HISTORY,
    FACE_MAX_INACTIVE_S,
)


class FaceTrack:
    """State container for a single tracked face."""
    __slots__ = ("track_id", "centroid", "velocity", "last_seen", "embedding_history", "id_cache", "smoothed_bbox", "pinned_identity", "recognition_backoff")

    def __init__(self, track_id: int, centroid: np.ndarray, embedding: np.ndarray, bbox: np.ndarray):
        self.track_id          = track_id
        self.centroid          = centroid
        self.velocity          = np.array([0.0, 0.0])
        self.last_seen         = time.time()
        self.embedding_history = deque([embedding], maxlen=FACE_TRACK_HISTORY)
        self.id_cache          = None   # last recognised identity dict
        self.smoothed_bbox     = bbox.astype(float)
        self.pinned_identity   = None   # Permanently stored identity for track life
        self.recognition_backoff = 0

    def update(self, centroid: np.ndarray, embedding: np.ndarray, bbox: np.ndarray):
        from config import INFERENCE_THROTTLE
        # Calculate velocity over the throttle period and normalize to a single frame step
        raw_velocity = centroid - self.centroid
        # Heavy smoothing for velocity and position
        beta = 0.8
        new_v = raw_velocity / max(1, INFERENCE_THROTTLE)
        self.velocity = beta * self.velocity + (1.0 - beta) * new_v
        
        self.centroid  = centroid
        self.last_seen = time.time()
        self.embedding_history.append(embedding)
        
        # Heavy smoothing (Alpha 0.1)
        alpha = 0.1
        self.smoothed_bbox = alpha * bbox.astype(float) + (1.0 - alpha) * self.smoothed_bbox

    def predict(self):
        """Linearly advance the box based on last velocity (prevents visual lag) with damping."""
        vx, vy = self.velocity
        self.smoothed_bbox[0] += vx
        self.smoothed_bbox[1] += vy
        self.smoothed_bbox[2] += vx
        self.smoothed_bbox[3] += vy
        
        # Advance centroid to match predicted bbox
        self.centroid[0] += vx
        self.centroid[1] += vy
        
        # Damping to prevent infinite drift
        self.velocity *= 0.95

    @property
    def avg_embedding(self) -> np.ndarray:
        return np.mean(self.embedding_history, axis=0)

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.last_seen) > FACE_MAX_INACTIVE_S


class FaceTracker:
    """
    Maintains a dict of active FaceTrack objects and matches
    incoming face detections to existing tracks by centroid proximity.
    """

    def __init__(self,
                 max_dist: float = FACE_TRACK_MAX_DIST,
                 max_inactive_s: float = FACE_MAX_INACTIVE_S):
        self._max_dist      = max_dist
        self._max_inactive  = max_inactive_s
        self._tracks: dict[int, FaceTrack] = {}
        self._id_counter    = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, faces: list, inf_scale: float) -> list[dict]:
        """
        Match each InsightFace detection to an existing track (or create one).
        Returns a list of dicts:
          { track_id, bbox, lmk2d, lmk3d, track }
        """
        used_ids   = set()
        parsed     = []

        for face in faces:
            bbox     = (face.bbox / inf_scale).astype(int)
            centroid = np.array([(bbox[0] + bbox[2]) / 2,
                                 (bbox[1] + bbox[3]) / 2])

            lmk2d = (face.landmark_2d_106 / inf_scale
                     if hasattr(face, "landmark_2d_106") and
                     face.landmark_2d_106 is not None else None)
            lmk3d = (face.landmark_3d_68[:, :2] / inf_scale
                     if hasattr(face, "landmark_3d_68") and
                     face.landmark_3d_68 is not None else None)

            # Match to nearest existing track
            matched_id  = None
            nearest_dist = self._max_dist
            for tid, track in self._tracks.items():
                if tid in used_ids:
                    continue
                dist = float(np.linalg.norm(centroid - track.centroid))
                if dist < nearest_dist:
                    nearest_dist = dist
                    matched_id   = tid

            if matched_id is not None:
                used_ids.add(matched_id)
                self._tracks[matched_id].update(centroid, face.embedding, bbox)
            else:
                self._id_counter += 1
                matched_id = self._id_counter
                self._tracks[matched_id] = FaceTrack(
                    matched_id, centroid, face.embedding, bbox
                )

            parsed.append({
                "track_id": matched_id,
                "bbox":     bbox,
                "lmk2d":   lmk2d,
                "lmk3d":   lmk3d,
                "track":   self._tracks[matched_id],
                "raw_face": face,
            })

        self._merge_duplicate_tracks()
        return parsed

    def _merge_duplicate_tracks(self):
        """Merge tracks whose centroids are extremely close to prevent redundant boxes."""
        tids = list(self._tracks.keys())
        merged = set()
        
        for i in range(len(tids)):
            tid1 = tids[i]
            if tid1 in merged or tid1 not in self._tracks: continue
            
            for j in range(i + 1, len(tids)):
                tid2 = tids[j]
                if tid2 in merged or tid2 not in self._tracks: continue
                
                t1 = self._tracks[tid1]
                t2 = self._tracks[tid2]
                
                dist = np.linalg.norm(t1.centroid - t2.centroid)
                # If centroids are within 30 pixels (approx 5% of 640px), they are likely duplicates
                if dist < 30.0:
                    # Merge t2 into t1 (keep t1 as it's the older track usually)
                    # We use the most recent last_seen
                    t1.last_seen = max(t1.last_seen, t2.last_seen)
                    # Merge embedding history
                    t1.embedding_history.extend(t2.embedding_history)
                    merged.add(tid2)
                    
        for tid in merged:
            self._tracks.pop(tid, None)

    def prune_stale(self):
        """Remove tracks that haven't been seen recently."""
        self._tracks = {
            tid: t for tid, t in self._tracks.items() if not t.is_stale
        }

    def get_avg_embedding(self, track_id: int) -> np.ndarray | None:
        t = self._tracks.get(track_id)
        return t.avg_embedding if t else None

    def clear(self):
        self._tracks.clear()

    def predict(self):
        """Advance all tracks based on their last known velocity."""
        for track in self._tracks.values():
            track.predict()

    def __len__(self) -> int:
        return len(self._tracks)
