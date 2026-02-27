# Ryuk AI - Real-time Face Tracking Server

A real-time face tracking and camera streaming server built with FastAPI, OpenCV, and [InsightFace](https://github.com/deepinsight/insightface). 

The server receives raw JPEG frames from a mobile client (via WebSockets), processes them to extract face bounding boxes and landmarks, and displays the tracking results in real-time in an OpenCV desktop window.

## Features

- **WebSocket Streaming**: Receives high-speed camera frames from iOS/Android mobile clients.
- **Face Analysis**: Utilizes InsightFace (`buffalo_l` model) for accurate face detection and facial landmarks detection.
- **Live Desktop Display**: Automatically rotates and displays the processed video feed with overlaid bounding boxes and keypoints.
- **Low Latency Architecture**: Uses deque-based frame dropping to ensure the displayed frame is always the most recent one, preventing queue backlog.

## Prerequisites

- Python 3.8+ (Tested on Python 3.12)
- C++ Build Tools (required for some Python dependencies like InsightFace)
- GPU support is supported via `ctx_id=0` internally but will fallback to CPU if not properly configured.

## Setup & Installation

1. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows, use: venv\Scripts\activate
   ```

2. **Install the dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   *Note: InsightFace may download the `buffalo_l` model on the first run. Make sure you have a stable internet connection.*

## Running the Server

Launch the server using Python:

```bash
python main.py
```

- Watch the terminal output for the local WebSocket URL (e.g., `ws://192.168.x.x:8000/ws/stream`).
- An OpenCV window named **Ryuk AI - Camera Stream** will open.
- To quit the server cleanly, click on the **Ryuk AI - Camera Stream** OpenCV window and press the **`Q`** key.

## Mobile Client Integration

Please refer to the detailed [Mobile Integration Guide](mobile_integration.md) for providing live streams from your iOS or Android applications to the Ryuk server endpoint. The server expects continuous raw JPEG-encoded bytes sent via binary WebSocket messages.
