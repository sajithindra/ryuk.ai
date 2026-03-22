import motor.motor_asyncio
import pymongo
import asyncio

from config import MONGO_URI, DB_NAME
from core.logger import logger
from core.exceptions import DatabaseError

# Async client for FastAPI / async routes
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

# Collection Handles
profiles_col = db["profiles"]
cameras_col = db["cameras"]
activity_logs_col = db["activity_logs"]

async def init_db():
    """Ensure indexes are created for performance with error trapping."""
    try:
        # Check connection
        await client.admin.command('ping')
        await profiles_col.create_index("aadhar", unique=True)
        await cameras_col.create_index("client_id", unique=True)
        await activity_logs_col.create_index([("aadhar", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)])
        await activity_logs_col.create_index([("client_id", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)])
        logger.info("MongoDB: Database and indexes initialized.")
    except Exception as e:
        logger.error(f"MongoDB: Init error (Unreachable): {e}")
        raise DatabaseError(f"Failed to initialize MongoDB: {e}") from e

# ---------------------------------------------------------------------------
# Sync client singleton – reused across health checks and watchdog operations.
# Creating a new MongoClient per call re-establishes a TCP connection each time.
# ---------------------------------------------------------------------------
_sync_client: pymongo.MongoClient | None = None

def get_sync_db():
    """Returns a cached synchronous MongoDB database handle."""
    global _sync_client
    try:
        if _sync_client is None:
            _sync_client = pymongo.MongoClient(
                MONGO_URI,
                serverSelectionTimeoutMS=2000,
                connectTimeoutMS=2000,
            )
        _sync_client.admin.command('ping')
        return _sync_client[DB_NAME]
    except Exception as e:
        logger.error(f"MongoDB Sync Error: {e}")
        _sync_client = None  # Force reconnect on next call
        raise DatabaseError(f"MongoDB Sync Error: {e}") from e

# Run init in the background event loop if one is already running,
# or it will be called by the server startup.
