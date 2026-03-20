import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.ai_processor import face_app
import onnxruntime as ort

detector = face_app.models['detection']
print(f"Detector class: {detector.__class__}")
print(f"Detector session: {detector.session}")

# Try to create IO binding
try:
    binding = detector.session.io_binding()
    print("Successfully created IO binding for detector")
except Exception as e:
    print(f"Failed to create IO binding: {e}")
