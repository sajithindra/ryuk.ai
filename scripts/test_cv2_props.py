import cv2
import os

# Test URL or dummy
url = "rtsp://localhost:8554/live" # Doesn't need to be reachable for the prop check usually

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "hwaccel;cuda"
cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)

print(f"Prop HW_ACCELERATION before: {cap.get(cv2.CAP_PROP_HW_ACCELERATION)}")
success = cap.set(cv2.CAP_PROP_HW_ACCELERATION, 4)
print(f"Set CUDA (4) Success: {success}")
print(f"Prop HW_ACCELERATION after: {cap.get(cv2.CAP_PROP_HW_ACCELERATION)}")

cap.release()
