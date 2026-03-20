import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    import onnxruntime as ort
    print(f"ONNX Runtime Version: {ort.__version__}")
    print(f"Available Providers: {ort.get_available_providers()}")
    
    from core.ai_processor import face_app
    print("\nInsightFace Model Status:")
    for model_name, model in face_app.models.items():
        active = model.session.get_providers()
        print(f"  Model: {model_name:15} | Task: {model.taskname:15} | Active Providers: {active}")
        
except Exception as e:
    print(f"Error checking GPU: {e}")
