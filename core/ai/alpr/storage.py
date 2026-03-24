import os
import cv2
import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from core.logger import logger

class ALPRStorage:
    def __init__(self, mongodb_uri, db_name, collection_name, image_base_path):
        self.client = AsyncIOMotorClient(mongodb_uri)
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]
        self.image_base_path = image_base_path
        
        os.makedirs(image_base_path, exist_ok=True)
        logger.info(f"ALPR Storage initialized (DB: {db_name})")

    async def setup_indexes(self):
        await self.collection.create_index("plate_number")
        await self.collection.create_index("timestamp")
        await self.collection.create_index("camera_id")
        logger.info("ALPR MongoDB indexes created")

    def save_plate_image(self, plate_crop, plate_number, camera_id):
        """
        Save cropped plate image to local storage.
        Path: /plates/YYYY/MM/DD/camera_id/plate_number_timestamp.jpg
        """
        now = datetime.datetime.now()
        date_path = now.strftime("%Y/%m/%d")
        dir_path = os.path.join(self.image_base_path, date_path, camera_id)
        os.makedirs(dir_path, exist_ok=True)
        
        filename = f"{plate_number}_{int(now.timestamp())}.jpg"
        file_path = os.path.join(dir_path, filename)
        
        cv2.imwrite(file_path, plate_crop)
        return file_path

    async def save_metadata(self, metadata):
        """
        metadata: dict matching the MongoDB schema
        """
        try:
            metadata["created_at"] = datetime.datetime.utcnow()
            await self.collection.insert_one(metadata)
            return True
        except Exception as e:
            logger.error(f"Failed to save metadata to MongoDB: {e}")
            return False

    async def get_plates(self, camera_id=None, start_time=None, end_time=None, limit=100):
        query = {}
        if camera_id:
            query["camera_id"] = camera_id
        if start_time or end_time:
            query["timestamp"] = {}
            if start_time:
                query["timestamp"]["$gte"] = start_time
            if end_time:
                query["timestamp"]["$lte"] = end_time
                
        cursor = self.collection.find(query).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_plate_details(self, plate_number):
        return await self.collection.find_one({"plate_number": plate_number})
