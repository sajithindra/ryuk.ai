from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn
from core.state import cache, new_stream_signals

app = FastAPI()

@app.websocket("/ws/stream")
async def websocket_camera_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_host = websocket.client.host
    client_port = websocket.client.port
    client_id = f"{client_host}:{client_port}"
    
    print(f"Camera client {client_id} connected via Redis Bridge.")
    
    # Register stream in Redis Set
    cache.sadd("registry:active_streams", client_id)
    # Signal UI (Legacy compatibility for current UI polling)
    new_stream_signals.append(client_id)
        
    try:
        while True:
            data = await websocket.receive_bytes()
            # PUSH TO REDIS with 2s expiration to prevent memory bloat
            frame_key = f"stream:{client_id}:frame"
            cache.set(frame_key, data, ex=2)
    except WebSocketDisconnect:
        print(f"Camera client {client_id} disconnected.")
    finally:
        # Cleanup Registry
        cache.srem("registry:active_streams", client_id)
        cache.delete(f"stream:{client_id}:frame")

@app.get("/")
def read_root():
    return {"message": "Ryuk AI - Streaming Server Running. Connect camera to /ws/stream."}

def run_server(host: str, port: int = 8000):
    """Runs the uvicorn server in a background thread."""
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
