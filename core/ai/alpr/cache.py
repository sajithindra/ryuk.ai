import redis
import time
from core.logger import logger

class ALPRCache:
    def __init__(self, redis_url, deduplication_ttl=30):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.ttl = deduplication_ttl
        logger.info(f"ALPR Redis Cache initialized (TTL: {deduplication_ttl}s)")

    def is_duplicate(self, plate_number, camera_id):
        """
        Check if plate has been seen recently.
        Key: alpr:dedup:camera_id:plate_number
        """
        key = f"alpr:dedup:{camera_id}:{plate_number}"
        if self.redis.get(key):
            return True
        
        # If not duplicate, set key with TTL
        self.redis.setex(key, self.ttl, str(time.time()))
        return False

    def publish_event(self, event_data):
        """
        Publish ALPR event to Redis stream/pub-sub
        """
        try:
            import json
            # Using Pub/Sub for real-time dashboard updates
            self.redis.publish("alpr:events", json.dumps(event_data))
            
            # Streams require all values to be strings
            stream_data = {k: str(v) for k, v in event_data.items()}
            self.redis.xadd("alpr:stream", stream_data)
        except Exception as e:
            logger.error(f"Failed to publish ALPR event: {e}")

    def push_ui_results(self, camera_id, data):
        """
        Push real-time tracking/OCR results to Redis for the UI Processor.
        """
        try:
            import json
            key = f"stream:{camera_id}:alpr_results"
            self.redis.rpush(key, json.dumps(data))
            self.redis.ltrim(key, -5, -1) # Keep only latest 5 packets
        except Exception as e:
            logger.error(f"Failed to push UI results: {e}")

    def get_health(self):
        try:
            return self.redis.ping()
        except:
            return False
