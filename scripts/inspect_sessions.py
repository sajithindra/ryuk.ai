import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.ai_processor import face_app
import onnxruntime as ort

print("Model Input Details:")
for name, model in face_app.models.items():
    inputs = model.session.get_inputs()
    outputs = model.session.get_outputs()
    print(f"\nModel: {name}")
    for i in inputs:
        print(f"  Input: {i.name} | Shape: {i.shape} | Type: {i.type}")
    for o in outputs:
        print(f"  Output: {o.name} | Shape: {o.shape} | Type: {o.type}")
