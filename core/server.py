from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn
import json
import asyncio
from core.state import cache, new_stream_signals

app = FastAPI()

# Track connected alert clients
alert_clients = set()

@app.websocket("/ws/stream")
async def websocket_camera_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_host = websocket.client.host
    client_port = websocket.client.port
    client_id = f"{client_host}:{client_port}"
    
    print(f"Camera client {client_id} connected via Redis Bridge.")
    cache.sadd("registry:active_streams", client_id)
    new_stream_signals.append(client_id)
    
    # Log to MongoDB (Async)
    from core.database import cameras_col
    from datetime import datetime
    await cameras_col.update_one(
        {"client_id": client_id},
        {"$set": {
            "host": client_host,
            "port": client_port,
            "last_connected": datetime.now(),
            "status": "online"
        }},
        upsert=True
    )
        
    try:
        while True:
            data = await websocket.receive_bytes()
            frame_key = f"stream:{client_id}:frame"
            cache.set(frame_key, data, ex=2)
    except WebSocketDisconnect:
        print(f"Camera client {client_id} disconnected.")
    finally:
        cache.srem("registry:active_streams", client_id)
        cache.delete(f"stream:{client_id}:frame")
        # Update status to offline
        await cameras_col.update_one(
            {"client_id": client_id},
            {"$set": {"status": "offline"}}
        )

@app.websocket("/ws/alerts")
async def alerts_endpoint(websocket: WebSocket):
    """WebSocket for system-wide security notifications."""
    await websocket.accept()
    alert_clients.add(websocket)
    print("Alert client connected to security channel.")
    
    # Listen to Redis Pub/Sub for alerts in background
    pubsub = cache.pubsub()
    pubsub.subscribe("security_alerts")
    
    try:
        # We run a loop to pump Redis messages to the WebSocket
        while True:
            # Non-blocking check for Redis messages
            msg = pubsub.get_message(ignore_subscribe_messages=True)
            if msg:
                alert_json = msg['data'].decode('utf-8')
                await websocket.send_text(alert_json)
            await asyncio.sleep(0.1)
    except Exception:
        pass
    finally:
        alert_clients.remove(websocket)
        print("Alert client disconnected.")

@app.get("/")
def read_root():
    return {"message": "Ryuk AI - Streaming Server Running. Connect camera to /ws/stream."}

def run_server(host: str, port: int = 8000):
    """Runs the uvicorn server in a background thread."""
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
