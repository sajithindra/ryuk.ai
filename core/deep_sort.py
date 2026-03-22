import numpy as np
from collections import deque
import time
from scipy.optimize import linear_sum_assignment

def iou(bbox1, bbox2):
    """Calculates Intersection over Union (IoU) between two bboxes."""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])
    
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
    union = area1 + area2 - intersection
    
    return intersection / union if union > 0 else 0

class KalmanFilter:
    """A simple 1D Kalman Filter for box coordinates [x1, y1, x2, y2]."""
    def __init__(self, bbox):
        # State: [x1, y1, x2, y2, dx1, dy1, dx2, dy2]
        self.x = np.zeros((8, 1))
        self.x[:4, 0] = bbox
        
        # Uncertainty covariance
        self.P = np.eye(8) * 10.0
        self.P[4:, 4:] *= 1000.0 # High initial uncertainty for velocity
        
        # State transition matrix (Constant Velocity Model)
        self.F = np.eye(8)
        self.F[0, 4] = self.F[1, 5] = self.F[2, 6] = self.F[3, 7] = 1.0
        
        # Observation matrix
        self.H = np.zeros((4, 8))
        self.H[:4, :4] = np.eye(4)
        
        # Process noise covariance
        self.Q = np.eye(8) * 0.01
        self.Q[4:, 4:] *= 0.01
        
        # Measurement noise covariance
        self.R = np.eye(4) * 1.0

    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.x[:4, 0]

    def update(self, bbox):
        z = bbox.reshape((4, 1))
        y = z - self.H @ self.x # Innovation
        S = self.H @ self.P @ self.H.T + self.R # Innovation covariance
        K = self.P @ self.H.T @ np.linalg.inv(S) # Kalman gain
        self.x = self.x + K @ y
        self.P = (np.eye(8) - K @ self.H) @ self.P

class DeepSortTrack:
    def __init__(self, track_id, bbox, face_embedding=None, raw_face=None):
        self.track_id = track_id
        self.kf = KalmanFilter(bbox)
        self.face_embedding = face_embedding
        self.raw_face = raw_face
        self.hits = 1
        self.state = 0 # 0: Tentative, 1: Confirmed, 2: Deleted
        self.pinned_identity = None
        self.id_cache = None
        
        self.time_since_update = 0
        
        # Real-time persistence
        self.last_update_time = time.time()
        self.last_predict_time = time.time()
        
        # For smoothing the display box
        self.smoothed_bbox = bbox.copy().astype(float)

    def predict(self):
        predicted = self.kf.predict()
        self.time_since_update += 1
        self.last_predict_time = time.time()
        
        # Robust Velocity Damping: 
        # If occluded or missing detections, slowly kill the velocity components
        # to prevent the box from 'flying away' into space.
        # Progressively kill velocity [dx1, dy1, dx2, dy2] if we haven't seen the face for a while.
        # Threshold increased to 30 frames (~1s at 30fps) to account for inference throttle
        # and brief head twists/occlusions without losing momentum too early.
        if self.time_since_update > 30:
             decay = max(0.5, 0.95 ** (self.time_since_update - 1))
             self.kf.x[4:] *= decay
        
        # Damping for display
        alpha = 0.8
        self.smoothed_bbox = alpha * predicted + (1.0 - alpha) * self.smoothed_bbox
        return predicted

    def update(self, bbox, face_embedding=None, raw_face=None):
        self.kf.update(bbox)
        self.raw_face = raw_face
        
        # Exponential moving average for embeddings
        alpha = 0.9
        
        if face_embedding is not None:
            if self.face_embedding is None:
                self.face_embedding = face_embedding
            else:
                self.face_embedding = alpha * self.face_embedding + (1.0 - alpha) * face_embedding
                norm = np.linalg.norm(self.face_embedding)
                if norm > 0: self.face_embedding /= norm
        
        self.hits += 1
        self.time_since_update = 0
        self.last_update_time = time.time()
        self.smoothed_bbox = bbox.copy().astype(float)
        
        from config import TRACKER_N_INIT
        if self.state == 0 and self.hits >= TRACKER_N_INIT:
            self.state = 1

    @property
    def is_stale(self) -> bool:
        from config import FACE_MAX_INACTIVE_S
        # USE REAL TIME instead of frame-ticks to avoid FPS mismatch issues
        # Especially when processing (5fps) is slower than input (30fps)
        elapsed = time.time() - self.last_update_time
        return elapsed > FACE_MAX_INACTIVE_S 

    @property
    def last_seen(self) -> float:
        from config import INPUT_FPS
        return time.time() - (self.time_since_update / float(INPUT_FPS))

    @property
    def avg_embedding(self) -> np.ndarray:
        return self.face_embedding

class DeepSortTracker:
    def __init__(self):
        from config import TRACKER_MAX_AGE, TRACKER_MATCH_THRESHOLD, TRACKER_IOU_THRESHOLD
        self.max_age = TRACKER_MAX_AGE
        self.match_threshold = TRACKER_MATCH_THRESHOLD
        self.iou_threshold = TRACKER_IOU_THRESHOLD
        self.tracks = {}
        self._next_id = 1

    def predict(self):
        for track in list(self.tracks.values()):
            track.predict()

    def update(self, faces, scale=1.0):
        """
        faces: list of InsightFace Face objects (or dicts)
        """
        detections = []
        face_embs = []
        raw_faces_list = []
        
        for f in faces:
            bbox = getattr(f, 'bbox', None)
            if bbox is None and isinstance(f, dict): bbox = f.get('bbox')
            emb = getattr(f, 'embedding', None)
            if emb is None and isinstance(f, dict): emb = f.get('embedding')
            
            if bbox is not None:
                detections.append(bbox)
                face_embs.append(emb)
                raw_faces_list.append(f)

        if not detections:
            # Just age existing tracks
            for tid, track in list(self.tracks.items()):
                # Delete strictly by REAL TIME staleness
                if track.is_stale:
                    track.state = 2
            self.tracks = {tid: t for tid, t in self.tracks.items() if t.state != 2}
            return

        detections = np.array(detections) / scale
        
        # 2. Matching by Appearance (Fused Cosine Distance)
        confirmed_ids = [tid for tid, t in self.tracks.items() if t.state == 1]
        
        matches = []
        unmatched_tracks = list(self.tracks.keys())
        unmatched_detections = list(range(len(detections)))
        
        if len(confirmed_ids) > 0 and len(detections) > 0:
            cost_matrix = np.zeros((len(confirmed_ids), len(detections)))
            for i, tid in enumerate(confirmed_ids):
                track = self.tracks[tid]
                for j in range(len(detections)):
                    d_face_emb = face_embs[j]
                    
                    dist_face = 1.0 # Max distance
                    
                    if track.face_embedding is not None and d_face_emb is not None:
                        dist_face = 1.0 - np.dot(track.face_embedding, d_face_emb)
                    
                    cost_matrix[i, j] = dist_face
            
            row_ind, col_ind = linear_sum_assignment(cost_matrix)
            for r, c in zip(row_ind, col_ind):
                if cost_matrix[r, c] < self.match_threshold:
                    tid = confirmed_ids[r]
                    matches.append((tid, c))
                    if tid in unmatched_tracks: unmatched_tracks.remove(tid)
                    if c in unmatched_detections: unmatched_detections.remove(c)

        # 2. Matching by IOU (for unmatched tracks and detections)
        if len(unmatched_tracks) > 0 and len(unmatched_detections) > 0:
            iou_matrix = np.zeros((len(unmatched_tracks), len(unmatched_detections)))
            for i, tid in enumerate(unmatched_tracks):
                track_bbox = self.tracks[tid].smoothed_bbox
                for j, d_idx in enumerate(unmatched_detections):
                    det_bbox = detections[d_idx]
                    iou_matrix[i, j] = iou(track_bbox, det_bbox)
            
            row_ind, col_ind = linear_sum_assignment(-iou_matrix) # maximize IOU
            for r, c in zip(row_ind, col_ind):
                if iou_matrix[r, c] > self.iou_threshold:
                    tid = unmatched_tracks[r]
                    det_idx = unmatched_detections[c]
                    matches.append((tid, det_idx))
                    
        # Remove matched items before distance matching
        matched_tids = [m[0] for m in matches]
        matched_didx = [m[1] for m in matches]
        unmatched_tracks = [t for t in unmatched_tracks if t not in matched_tids]
        unmatched_detections = [d for d in unmatched_detections if d not in matched_didx]

        # 3. Matching by Center Distance (Fallback for low FPS Fast-Movers)
        if len(unmatched_tracks) > 0 and len(unmatched_detections) > 0:
            from config import FACE_TRACK_MAX_DIST
            
            def bbox_center(bbox):
                return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
                
            dist_matrix = np.zeros((len(unmatched_tracks), len(unmatched_detections)))
            for i, tid in enumerate(unmatched_tracks):
                track_c = bbox_center(self.tracks[tid].smoothed_bbox)
                for j, d_idx in enumerate(unmatched_detections):
                    det_c = bbox_center(detections[d_idx])
                    dist_matrix[i, j] = np.sqrt((track_c[0] - det_c[0])**2 + (track_c[1] - det_c[1])**2)
            
            row_ind, col_ind = linear_sum_assignment(dist_matrix) # minimize Distance
            for r, c in zip(row_ind, col_ind):
                if dist_matrix[r, c] < FACE_TRACK_MAX_DIST:
                    tid = unmatched_tracks[r]
                    det_idx = unmatched_detections[c]
                    matches.append((tid, det_idx))
                    
        # Remove matched items before handling New Tracks
        matched_tids = [m[0] for m in matches]
        matched_didx = [m[1] for m in matches]
        unmatched_tracks = [t for t in unmatched_tracks if t not in matched_tids]
        unmatched_detections = [d for d in unmatched_detections if d not in matched_didx]
        
        # Apply Matches
        for tid, det_idx in matches:
            self.tracks[tid].update(
                detections[det_idx], 
                face_embedding=face_embs[det_idx], 
                raw_face=raw_faces_list[det_idx]
            )

        # 3. Handle Unmatched Detections (New Tracks)
        for det_idx in unmatched_detections:
            self.tracks[self._next_id] = DeepSortTrack(
                self._next_id, 
                detections[det_idx], 
                face_embedding=face_embs[det_idx], 
                raw_face=raw_faces_list[det_idx]
            )
            self._next_id += 1

        # 4. Handle Unmatched Tracks (Ageing)
        for tid in unmatched_tracks:
            # Delete strictly by REAL TIME staleness
            if self.tracks[tid].is_stale:
                self.tracks[tid].state = 2 # Deleted

        # Cleanup Deleted Tracks
        self.tracks = {tid: t for tid, t in self.tracks.items() if t.state != 2}

    def clear(self):
        self.tracks.clear()
        self._next_id = 1
