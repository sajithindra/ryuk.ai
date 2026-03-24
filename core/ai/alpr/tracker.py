import time
import numpy as np
from core.deep_sort import iou

class PlateTrack:
    def __init__(self, track_id, bbox, class_id=-1, label="Unknown"):
        self.track_id = track_id
        self.bbox = np.array(bbox)
        self.class_id = class_id
        self.label = label
        self.hits = 1
        self.age = 0
        self.last_seen = time.time()
        self.plate_text = None
        self.ocr_confidence = 0.0
        self.ocr_completed = False
        self.is_deleted = False

    def update(self, bbox, class_id=-1, label="Unknown"):
        self.bbox = np.array(bbox)
        self.class_id = class_id
        if label != "Unknown":
            self.label = label
        self.hits += 1
        self.age = 0
        self.last_seen = time.time()

class PlateTracker:
    def __init__(self, max_age=30, iou_threshold=0.1):
        self.max_age = max_age
        self.iou_threshold = iou_threshold
        self.tracks = []
        self.next_id = 1

    def update(self, detections):
        """
        detections: list of dicts with 'bbox'
        """
        # 1. Predict (Age existing tracks)
        for t in self.tracks:
            t.age += 1
            
        # 2. Match
        unmatched_detections = list(range(len(detections)))
        matched_tracks = []
        
        if self.tracks:
            # Create IOU matrix
            iou_matrix = np.zeros((len(self.tracks), len(detections)))
            for i, track in enumerate(self.tracks):
                for j, det in enumerate(detections):
                    iou_matrix[i, j] = iou(track.bbox, det['bbox'])
            
            # Simple greedy matching
            for i in range(len(self.tracks)):
                if len(unmatched_detections) == 0: break
                
                best_det_idx = -1
                max_iou = self.iou_threshold
                
                for j in unmatched_detections:
                    if iou_matrix[i, j] > max_iou:
                        max_iou = iou_matrix[i, j]
                        best_det_idx = j
                
                if best_det_idx != -1:
                    self.tracks[i].update(
                        detections[best_det_idx]['bbox'],
                        detections[best_det_idx].get('class_id', -1),
                        detections[best_det_idx].get('label', "Unknown")
                    )
                    matched_tracks.append(i)
                    unmatched_detections.remove(best_det_idx)

        # 3. Create new tracks
        for idx in unmatched_detections:
            new_track = PlateTrack(
                self.next_id, 
                detections[idx]['bbox'],
                detections[idx].get('class_id', -1),
                detections[idx].get('label', "Unknown")
            )
            self.tracks.append(new_track)
            self.next_id += 1

        # 4. Cleanup
        # If last_seen is too old or age is too high
        active_tracks = []
        for t in self.tracks:
            elapsed = time.time() - t.last_seen
            if elapsed < 2.0 and t.age < self.max_age:
                active_tracks.append(t)
            else:
                t.is_deleted = True
        
        self.tracks = active_tracks
        return self.tracks
