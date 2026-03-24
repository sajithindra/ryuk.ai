import cv2
import time
import asyncio
import numpy as np
from typing import Dict
from core.logger import logger
from core.ai.alpr.detector import PlateDetector
from core.ai.alpr.ocr import PlateOCR
from core.ai.alpr.tracker import PlateTracker
from core.ai.alpr.storage import ALPRStorage
from core.ai.alpr.cache import ALPRCache
from core.ai.alpr.utils import detect_color
from core.ingestion import get_ingestor

class ALPRPipeline:
    def __init__(self, config: Dict):
        self.config = config
        self.detector = PlateDetector(
            conf_threshold=config['alpr']['detection']['conf_threshold'],
            device=config['alpr']['detection']['device']
        )
        self.ocr_refiner = PlateOCR() # Use for specialized validation/normalization
        self.storage = ALPRStorage(
            mongodb_uri=config['alpr']['storage']['mongodb_uri'],
            db_name=config['alpr']['storage']['db_name'],
            collection_name=config['alpr']['storage']['collection_name'],
            image_base_path=config['alpr']['storage']['image_base_path']
        )
        self.cache = ALPRCache(
            redis_url=config['alpr']['cache']['redis_url'],
            deduplication_ttl=config['alpr']['cache']['deduplication_ttl_sec']
        )
        
        self.trackers: Dict[str, PlateTracker] = {}
        self.ingestors: Dict[str, any] = {}
        self.camera_tasks: Dict[str, asyncio.Task] = {}
        self.running = False
        
    async def start(self):
        self.running = True
        await self.storage.setup_indexes()
        logger.info("ALPR Pipeline started")

    async def add_camera(self, camera_id: str, rtsp_url: str):
        if camera_id in self.camera_tasks:
            return
            
        ingestor = get_ingestor(camera_id, rtsp_url)
        ingestor.start()
        self.ingestors[camera_id] = ingestor
        if camera_id not in self.trackers:
            self.trackers[camera_id] = PlateTracker(
                max_age=self.config['alpr']['tracking']['max_age']
            )
            
        # Start worker task immediately
        task = asyncio.create_task(self._camera_worker(camera_id))
        self.camera_tasks[camera_id] = task
        logger.info(f"Camera {camera_id} worker started in ALPR pipeline")

    async def stop(self):
        self.running = False
        for task in self.camera_tasks.values():
            task.cancel()
        for ingestor in self.ingestors.values():
            ingestor.stop()
        logger.info("ALPR Pipeline stopped")

    def _apply_motion_filter(self, frame, prev_frame, threshold=500):
        if prev_frame is None:
            return True, frame.copy()
            
        fg_mask = cv2.absdiff(cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY), 
                              cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        _, fg_mask = cv2.threshold(fg_mask, 25, 255, cv2.THRESH_BINARY)
        motion_score = np.count_nonzero(fg_mask)
        
        return motion_score > threshold, frame.copy()

    async def process_loop(self):
        """Persistent loop that stays alive while the pipeline is running."""
        while self.running:
            await asyncio.sleep(1)

    async def _camera_worker(self, camera_id: str):
        ingestor = self.ingestors[camera_id]
        tracker = self.trackers[camera_id]
        frame_count = 0
        prev_frame = None
        
        # FPS Control
        target_fps = self.config['alpr']['pipeline']['target_fps']
        frame_interval = 1.0 / target_fps
        
        while self.running:
            start_time = time.time()
            frame = ingestor.read_frame()
            frame_count += 1
            
            if frame is None:
                await asyncio.sleep(0.01)
                continue
                
            # 1. Motion Filter
            has_motion, current_gray = self._apply_motion_filter(
                frame, prev_frame, 
                self.config['alpr']['pipeline']['motion_threshold']
            )
            prev_frame = frame
            
            # Hybrid Logic: Force detection if motion OR periodic frame (every 30 frames) 
            periodic_check = (frame_count % 30 == 0)
            pending_ocr = any(not t.ocr_completed for t in tracker.tracks)

            should_process = True # has_motion or periodic_check or pending_ocr
            
            if not should_process and self.config['alpr']['pipeline']['motion_filter_enabled']:
                # Still update tracker with empty detections to age tracks
                tracker.update([])
                await asyncio.sleep(max(0, frame_interval - (time.time() - start_time)))
                continue


            # 2. Detection (FastALPR)
            detections = self.detector.detect(frame)
            if detections:
                logger.debug(f"Camera {camera_id}: Detected {len(detections)} potential plates")
            
            # 3. Tracking (PlateTracker)
            tracks = tracker.update(detections)
            
            # 4. OCR & Storage (Only for new or updated tracks)
            for track in tracks:
                # Find matching detection robustly (using highest IOU if exact bbox fails)
                matching_det = None
                max_iou = 0.5
                for d in detections:
                    from core.deep_sort import iou
                    d_iou = iou(track.bbox, np.array(d['bbox']))
                    if d_iou > max_iou:
                        max_iou = d_iou
                        matching_det = d
                
                if not matching_det:
                    continue

                if not track.ocr_completed and track.hits >= self.config['alpr']['tracking']['n_init']:
                    ocr_text = matching_det.get('ocr_text')
                    ocr_conf = matching_det.get('ocr_conf', 0.0)
                    
                    if ocr_text:
                        print(f"DEBUG: ALPR Pipeline - Raw OCR: '{ocr_text}' (Conf: {ocr_conf:.2f})", flush=True)
                        # Validate Indian Plate format using refiner
                        validated_plate = self.ocr_refiner.validate_indian_plate(ocr_text)
                        
                        if validated_plate:
                            logger.info(f"Camera {camera_id}: [VALIDATED] {validated_plate} (Conf: {ocr_conf:.2f})")
                            # Set track details
                            track.plate_text = validated_plate
                            track.ocr_confidence = float(ocr_conf)
                            track.ocr_completed = True
                        else:
                            print(f"DEBUG: ALPR Pipeline - Validation FAILED for '{ocr_text}'", flush=True)
                            # 4.1 High-Quality Plate Image Extraction
                            x1, y1, x2, y2 = map(int, track.bbox)
                            h_f, w_f = frame.shape[:2]
                            margin = 10 # Better margin for human readability
                            x1_c, y1_c = int(max(0, x1 - margin)), int(max(0, y1 - margin))
                            x2_c, y2_c = int(min(w_f, x2 + margin)), int(min(h_f, y2 + margin))
                            
                            plate_crop = frame[y1_c:y2_c, x1_c:x2_c]
                            
                            if plate_crop.size > 0:
                                # Deduplication
                                if not self.cache.is_duplicate(validated_plate, camera_id):
                                    # Persistence
                                    img_path = self.storage.save_plate_image(plate_crop, validated_plate, camera_id)
                                    metadata = {
                                        "plate_number": validated_plate,
                                        "camera_id": camera_id,
                                        "timestamp": time.time(),
                                        "confidence": float(ocr_conf),
                                        "image_path": img_path,
                                        "bbox": track.bbox.tolist()
                                    }
                                    await self.storage.save_metadata(metadata)
                                    self.cache.publish_event(metadata)
                                    
                                    track.plate_text = validated_plate
                                    track.ocr_confidence = ocr_conf
                                    track.ocr_completed = True
                                    logger.info(f"FastALPR Plate Detected: {validated_plate} from {camera_id}")

            # 5. Push real-time results to UI (Redis)
            ui_tracks = []
            for track in tracker.tracks: # Assuming PlateTracker has 'tracks' attribute
                ui_tracks.append({
                    "bbox": track.bbox.tolist(),
                    "plate": track.plate_text,
                    "conf": track.ocr_confidence,
                    "label": "License Plate"
                })
            self.cache.push_ui_results(camera_id, {"plates": ui_tracks})

            # Wait for next frame bucket
            elapsed = time.time() - start_time
            await asyncio.sleep(max(0, frame_interval - elapsed))
