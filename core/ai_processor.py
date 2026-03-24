"""
core/ai_processor.py
Legacy wrapper for the modular Global AI Processor.
"""
from core.ai.engine import GlobalAIProcessor
import threading

# Singleton instance
_instance = None
_lock = threading.Lock()

def get_ai_processor():
    global _instance
    with _lock:
        if _instance is None:
            _instance = GlobalAIProcessor()
        return _instance

# Export face_app for backward compatibility and services
face_app = get_ai_processor()

