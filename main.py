from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import cv2
import numpy as np
import threading
import uvicorn
import socket
from collections import deque
from insightface.app import FaceAnalysis

app = FastAPI()

print("Initializing InsightFace model...")
# Initialize InsightFace analysis. We specify ctx_id=0 to try using GPU for fast inference.
face_app = FaceAnalysis(name='buffalo_l')
face_app.prepare(ctx_id=0, det_size=(640, 640))
print("InsightFace model initialized successfully.")

# Thread-safe queue: maxlen=2 keeps only the latest frames, discarding stale ones
frame_queue = deque(maxlen=2)

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


def run_server(host: str):
    """Runs the uvicorn server in a background thread."""
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    # Get local IP for display
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()

    print("*" * 50)
    print(f"* Server running at: ws://{IP}:8000/ws/stream")
    print("*" * 50)

    # Start the uvicorn server in a background thread
    server_thread = threading.Thread(target=run_server, args=(IP,), daemon=True)
    server_thread.start()

    # --- OpenCV display MUST run on the main thread ---
    cv2.namedWindow("Ryuk AI - Camera Stream", cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL)
    cv2.resizeWindow("Ryuk AI - Camera Stream", 960, 540)

    print("Qt window open. Press 'Q' to quit.")
    while True:
        if frame_queue:
            data = frame_queue.popleft()
            nparr = np.frombuffer(data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is not None:
                # Rotate 90 degrees counter-clockwise to fix left-rotated mobile streams
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

                # Process frame with InsightFace
                faces = face_app.get(frame)
                
                # Iterate through detected faces and draw bounding boxes and landmarks
                for face in faces:
                    bbox = face.bbox.astype(int)
                    cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
                    
                    if hasattr(face, 'kps') and face.kps is not None:
                        kps = face.kps.astype(int)
                        for kp in kps:
                            cv2.circle(frame, (kp[0], kp[1]), 2, (0, 0, 255), 2)

                cv2.imshow("Ryuk AI - Camera Stream", frame)

        # waitKey must be called regularlyin the main loop to keep
        # the Qt event loop alive and process GUI events
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()
