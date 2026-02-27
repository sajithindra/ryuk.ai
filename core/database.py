import motor.motor_asyncio
import pymongo
import asyncio

# MongoDB Connection Configuration
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "ryuk_ai"

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
        print("MongoDB: Database and indexes initialized.")
    except Exception as e:
        print(f"MongoDB: Init error (Unreachable): {e}")

def get_sync_db():
    """Provides a synchronous handle with connection verification."""
    try:
        sync_client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        sync_client.admin.command('ping')
        return sync_client[DB_NAME]
    except Exception as e:
        print(f"MongoDB Sync Error: {e}")
        return None

# Run init in the background event loop if one is already running, 
# or it will be called by the server startup.
