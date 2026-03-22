import os
import sys
import inspect
sys.path.append(os.getcwd())
try:
    from core.ai_processor import GlobalAIProcessor
    p = GlobalAIProcessor(det_size=(640,640))
    person_det = p.person_det
    
    print("--- SOURCE OF person_det.detect ---")
    print(inspect.getsource(person_det.detect))
    print("--- END SOURCE ---")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
