import time
import cv2
import numpy as np

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from core.state import cache
from core.ai_processor import face_app
import core.watchdog_indexer as watchdog
from collections import deque
import json
import hashlib

class VideoProcessor(QThread):
    """
    Background Thread that reads from a specific client's Redis key, 
    runs InsightFace detection, and emits processed frames to the GUI.
    """
    frame_ready = pyqtSignal(QImage)
    stream_inactive = pyqtSignal(str) # Emits client_id

    def __init__(self, client_id):
        super().__init__()
        self.client_id = client_id
        self.running = True
        # Track storage: {track_id: {'history': deque, 'centroid': (x,y), 'last_seen': time}}
        self.tracks = {}
        self.track_id_counter = 0
        self.target_size = (640, 480) 

    def set_target_size(self, width, height):
        if width > 0 and height > 0:
            self.target_size = (width, height)

    def draw_delaunay(self, img, points, color=(0, 255, 0)):
        size = img.shape
        rect = (0, 0, size[1], size[0])
        subdiv = cv2.Subdiv2D(rect)
        for p in points:
            if 0 <= p[0] < size[1] and 0 <= p[1] < size[0]:
                subdiv.insert((float(p[0]), float(p[1])))
        triangleList = subdiv.getTriangleList()
        for t in triangleList:
            pt1 = (int(t[0]), int(t[1]))
            pt2 = (int(t[2]), int(t[3]))
            pt3 = (int(t[4]), int(t[5]))
            if (0 <= pt1[0] < size[1] and 0 <= pt1[1] < size[0] and
                0 <= pt2[0] < size[1] and 0 <= pt2[1] < size[0] and
                0 <= pt3[0] < size[1] and 0 <= pt3[1] < size[0]):
                cv2.line(img, pt1, pt2, color, 1, cv2.LINE_AA)
                cv2.line(img, pt2, pt3, color, 1, cv2.LINE_AA)
                cv2.line(img, pt3, pt1, color, 1, cv2.LINE_AA)

    def run(self):
        last_frame_time = 0
        is_active = False
        frame_key = f"stream:{self.client_id}:frame"

        while self.running:
            # PULL LATEST FRAME FROM REDIS
            data = cache.get(frame_key)
            
            if data:
                try:
                    nparr = np.frombuffer(data, np.uint8)
                    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                except Exception:
                    continue
                
                if frame is not None:
                    last_frame_time = time.time()
                    if not is_active:
                        is_active = True
                        
                    # Fix orientation
                    frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    frame = cv2.flip(frame, 1)

                    faces = face_app.get(frame)
                    now = time.time()
                    self.tracks = {tid: t for tid, t in self.tracks.items() if now - t['last_seen'] < 2.0}

                    used_tracks = set()
                    for face in faces:
                        bbox = face.bbox.astype(int)
                        f_centroid = np.array([(bbox[0]+bbox[2])/2, (bbox[1]+bbox[3])/2])
                        matched_id = None
                        min_dist = 120 
                        
                        for tid, track in self.tracks.items():
                            if tid in used_tracks: continue
                            dist = np.linalg.norm(f_centroid - track['centroid'])
                            if dist < min_dist:
                                min_dist = dist
                                matched_id = tid
                        
                        if matched_id is not None:
                            used_tracks.add(matched_id)
                            track = self.tracks[matched_id]
                            track['centroid'] = f_centroid
                            track['last_seen'] = now
                            track['history'].append(face.embedding)
                        else:
                            self.track_id_counter += 1
                            matched_id = self.track_id_counter
                            self.tracks[matched_id] = {
                                'history': deque([face.embedding], maxlen=5),
                                'centroid': f_centroid,
                                'last_seen': now,
                                'id_cache': None # Recognition cache per track
                            }
                        
                        # -- RECOGNITION WITH REDIS CACHING --
                        track = self.tracks[matched_id]
                        name = "Unknown"
                        
                        # Generate a fast hash of the embedding for caching
                        emb_hash = hashlib.md5(face.embedding.tobytes()).hexdigest()
                        cache_key = f"cache:face:{emb_hash}"
                        
                        # 1. Check Redis Cache First
                        cached_id = cache.get(cache_key)
                        if cached_id:
                            name = cached_id.decode('utf-8')
                        else:
                            # 2. Fallback to FAISS
                            avg_emb = np.mean(track['history'], axis=0)
                            identity = watchdog.recognize_face(avg_emb, threshold=0.45)
                            if identity:
                                name = identity.get("name", "Unknown")
                                # Save to Redis cache for 15 seconds
                                cache.set(cache_key, name, ex=15)
                        
                        cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (255, 0, 0), 1)
                        cv2.putText(frame, name.upper(), (bbox[0], bbox[1] - 15), 
                                    cv2.FONT_HERSHEY_DUPLEX, 0.7, (0, 255, 255), 1)

                        mesh_points = []
                        if hasattr(face, 'landmark_2d_106') and face.landmark_2d_106 is not None:
                            mesh_points.extend(face.landmark_2d_106)
                        if hasattr(face, 'landmark_3d_68') and face.landmark_3d_68 is not None:
                            mesh_points.extend(face.landmark_3d_68[:, :2])
                        if mesh_points:
                            self.draw_delaunay(frame, np.array(mesh_points), color=(0, 255, 0))

                    # Scale and Emit
                    h, w = frame.shape[:2]
                    target_w, target_h = self.target_size
                    scale = min(target_w / w, target_h / h)
                    nw, nh = int(w * scale), int(h * scale)
                    if nw > 0 and nh > 0:
                        scaled_frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
                    else:
                        scaled_frame = frame

                    rgb_frame = cv2.cvtColor(scaled_frame, cv2.COLOR_BGR2RGB)
                    sh, sw, sch = rgb_frame.shape
                    qt_img = QImage(rgb_frame.data, sw, sh, sch * sw, QImage.Format.Format_RGB888)
                    self.frame_ready.emit(qt_img.copy())
            else:
                if is_active and (time.time() - last_frame_time > 1.5):
                    is_active = False
                    self.tracks.clear()
                    self.stream_inactive.emit(self.client_id)
            self.msleep(10)

    def stop(self):
        self.running = False
        self.wait()
