import os
import sys
import inspect
sys.path.append(os.getcwd())
try:
    from core.ai_processor import GlobalAIProcessor
    p = GlobalAIProcessor(det_size=(640,640))
    det_model = p.app.models['detection']
    person_det = p.person_det
    
    print(f"Detection detect signature: {inspect.signature(det_model.detect)}")
    print(f"Person detect signature: {inspect.signature(person_det.detect)}")
    
    # Also check if it's a bound method or something else
    print(f"Detection detect is method: {inspect.ismethod(det_model.detect)}")
    print(f"Person detect is method: {inspect.ismethod(person_det.detect)}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
