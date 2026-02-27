from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn
from core.state import frame_queue

app = FastAPI()

@app.websocket("/ws/stream")
async def websocket_camera_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Camera client connected to /ws/stream")
    try:
        while True:
            data = await websocket.receive_bytes()
            frame_queue.append(data)
    except WebSocketDisconnect:
        print("Camera client disconnected")
    except Exception as e:
        print(f"Error reading camera websocket: {e}")

@app.get("/")
def read_root():
    return {"message": "Ryuk AI - Streaming Server Running. Connect camera to /ws/stream."}

def run_server(host: str, port: int = 8000):
    """Runs the uvicorn server in a background thread."""
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
