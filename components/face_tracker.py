from core.deep_sort import DeepSortTracker
import numpy as np

class FaceTracker:
    def __init__(self):
        self._tracker = DeepSortTracker()

    def update(self, faces: list, inf_scale: float = 1.0) -> list[dict]:
        """
        Input: InsightFace list[Face]
        Output: list[dict] with 'track', 'track_id', 'bbox', 'raw_face'
        """
        self._tracker.update(faces, scale=inf_scale)
        
        parsed = []
        for tid, track in self._tracker.tracks.items():
            parsed.append({
                "track": track,
                "track_id": tid,
                "bbox": track.smoothed_bbox.astype(int),
                "raw_face": getattr(track, "raw_face", None)
            })
            
        return parsed

    def predict(self):
        self._tracker.predict()

    def clear(self):
        self._tracker.clear()
        
    def prune_stale(self):
        # Internally handled in DeepSortTracker.update
        pass

    @property
    def _tracks(self):
        return self._tracker.tracks
