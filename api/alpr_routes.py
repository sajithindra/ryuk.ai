from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from datetime import datetime
from core.ai.alpr.storage import ALPRStorage
import os
import yaml

router = APIRouter(prefix="/plates", tags=["ALPR"])

# Global storage instance (will be initialized by main app)
storage: Optional[ALPRStorage] = None

def init_router(config_path):
    global storage
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    storage = ALPRStorage(
        mongodb_uri=config['alpr']['storage']['mongodb_uri'],
        db_name=config['alpr']['storage']['db_name'],
        collection_name=config['alpr']['storage']['collection_name'],
        image_base_path=config['alpr']['storage']['image_base_path']
    )

@router.get("/")
async def list_plates(
    camera_id: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: int = Query(100, le=1000)
):
    if not storage:
        raise HTTPException(status_code=500, detail="ALPR Storage not initialized")
    
    # Convert floats to datetime if needed or use directly if storage handles it
    results = await storage.get_plates(camera_id, start_time, end_time, limit)
    # Clean up _id for JSON serialization
    for res in results:
        res["_id"] = str(res["_id"])
    return results

@router.get("/{plate_number}")
async def get_plate(plate_number: str):
    if not storage:
        raise HTTPException(status_code=500, detail="ALPR Storage not initialized")
    
    result = await storage.get_plate_details(plate_number)
    if not result:
        raise HTTPException(status_code=404, detail="Plate not found")
        
    result["_id"] = str(result["_id"])
    return result

@router.get("/cameras/{camera_id}")
async def list_camera_plates(camera_id: str, limit: int = 100):
    return await list_plates(camera_id=camera_id, limit=limit)
