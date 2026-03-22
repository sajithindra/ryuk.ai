import os
import sys
# Add current directory to path
sys.path.append(os.getcwd())
try:
    from core.ai_processor import GlobalAIProcessor
    p = GlobalAIProcessor(det_size=(640,640))
    print(f"Detection model type: {type(p.app.models['detection'])}")
    print(f"Person model type: {type(p.person_det)}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
