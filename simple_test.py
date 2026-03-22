#!/usr/bin/env python3
import cv2
import asyncio
import websockets

async def send_video_frames():
    uri = 'ws://localhost:8000/ws/stream'
    source = 0
    
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to {}".format(uri))

            cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                print("Failed to open video source")
                return

            print("Opened video source")
            frame_count = 0

            try:
                while frame_count < 10:  # Just send 10 frames for testing
                    ret, frame = cap.read()
                    if not ret:
                        print("Failed to read frame")
                        break

                    frame = cv2.resize(frame, (640, 480))
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                    _, encoded_img = cv2.imencode('.jpg', frame, encode_param)

                    await websocket.send(encoded_img.tobytes())
                    frame_count += 1
                    print("Sent frame {}".format(frame_count))

                    await asyncio.sleep(0.1)

            finally:
                cap.release()

    except Exception as e:
        print("Error: {}".format(e))

if __name__ == "__main__":
    asyncio.run(send_video_frames())