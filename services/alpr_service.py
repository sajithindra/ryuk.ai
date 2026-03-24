import os
import sys

# Add project root to sys.path before any local imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Disable PaddleOCR's slow connectivity check on startup
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

import asyncio
import yaml
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.logger import logger
from core.ai.alpr.pipeline import ALPRPipeline
from api.alpr_routes import router as alpr_router, init_router
from core.database import cameras_col

# Global pipeline instance
pipeline = None

async def monitor_cameras():
    """
    Periodically check MongoDB for new cameras and add them to the pipeline.
    """
    global pipeline
    seen_cameras = set()
    
    while True:
        try:
            async for camera in cameras_col.find():
                client_id = camera.get("client_id")
                
                if client_id and client_id not in seen_cameras:
                    # Use Redis bridge instead of direct RTSP to avoid redundant decoding
                    await pipeline.add_camera(client_id, None)
                    seen_cameras.add(client_id)
                    logger.info(f"ALPR Service: Monitoring camera {client_id}")

                    
        except Exception as e:
            logger.error(f"ALPR Service: Camera monitor error: {e}")
            
        await asyncio.sleep(10)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "alpr_config.yaml")
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Initialize API storage
    init_router(config_path)
    
    # Initialize Pipeline
    pipeline = ALPRPipeline(config)
    await pipeline.start()
    
    # Start tasks
    monitor_task = asyncio.create_task(monitor_cameras())
    process_task = asyncio.create_task(pipeline.process_loop())
    
    logger.info("ALPR Service Startup Complete")
    
    yield
    
    # Shutdown
    if pipeline:
        await pipeline.stop()
    monitor_task.cancel()
    process_task.cancel()
    logger.info("ALPR Service Shutdown Complete")

app = FastAPI(title="Ryuk AI - ALPR Service", lifespan=lifespan)
app.include_router(alpr_router)

if __name__ == "__main__":
    # In production, use environment variables for port
    port = int(os.getenv("ALPR_PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
