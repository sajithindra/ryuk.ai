#!/usr/bin/env python3
"""
Test script to simulate video input by reading from webcam or video file
and sending frames to the Ryuk AI WebSocket endpoint.
"""
import cv2
import asyncio
import websockets
import sys
import os

async def send_video_frames(uri, source=0):
    """
    Connect to WebSocket and send video frames.
    source: 0 for webcam, or path to video file
    """
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to {}".format(uri))

            # Open video source
            cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                print("Failed to open video source: {}".format(source))
                return

            print("Opened video source: {}".format(source))
            frame_count = 0

            try:
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        print("End of video or failed to read frame")
                        break

                    # Resize frame for better performance
                    frame = cv2.resize(frame, (640, 480))

                    # Encode as JPEG
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                    _, encoded_img = cv2.imencode('.jpg', frame, encode_param)

                    # Send as binary
                    await websocket.send(encoded_img.tobytes())

                    frame_count += 1
                    if frame_count % 30 == 0:
                        print("Sent {} frames".format(frame_count))

                    # Small delay to simulate real-time streaming
                    await asyncio.sleep(0.033)  # ~30 FPS

            except KeyboardInterrupt:
                print("Interrupted by user")
            except Exception as e:
                print("Error: {}".format(e))
            finally:
                cap.release()

    except Exception as e:
        print("Connection failed: {}".format(e))

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Send video frames to Ryuk AI WebSocket')
    parser.add_argument('--uri', default='ws://localhost:8000/ws/stream',
                       help='WebSocket URI (default: ws://localhost:8000/ws/stream)')
    parser.add_argument('--source', default=0,
                       help='Video source: 0 for webcam, or path to video file')

    args = parser.parse_args()

    print("Starting video sender to {}".format(args.uri))
    print("Video source: {}".format(args.source))

    asyncio.run(send_video_frames(args.uri, args.source))</content>
<parameter name="file_path">/home/sajithindra/Projects/ryuk.ai/test_video_sender.py