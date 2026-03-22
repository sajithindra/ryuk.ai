import os
import sys
import inspect
sys.path.append(os.getcwd())
try:
    from core.ai_processor import GlobalAIProcessor
    p = GlobalAIProcessor(det_size=(640,640))
    person_det = p.person_det
    
    src = inspect.getsource(person_det.detect)
    lines = src.split('\n')
    print("--- SIGNATURE ---")
    for line in lines[:5]:
        print(line)
    print("--- END SIGNATURE ---")
    
except Exception as e:
    print(f"Error: {e}")
