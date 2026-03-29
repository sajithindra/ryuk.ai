"""
core/watchdog_indexer.py
Shim layer for the modular WatchdogIndexer.
Maintains backward compatibility for existing imports.
"""
from core.registry.indexer import WatchdogIndexer
from config import FAISS_THRESHOLD

# Singleton instance
_indexer = WatchdogIndexer()

def update_faiss_index():           _indexer.update_index()
def rebuild_index_background():     return threading.Thread(target=_indexer.update_index, daemon=True).start()
def enroll_face(*a, **kw):          _indexer.enroll_face(*a, **kw)
def recognize_face(emb, threshold=FAISS_THRESHOLD, **kwargs):
    return _indexer.recognize_face(emb, threshold, **kwargs)
def log_activity(aadhar, client_id, action="Unknown"): _indexer.log_activity(aadhar, client_id, action)
def get_profile(aadhar):             return _indexer._profiles_col.find_one({"aadhar": aadhar})
def get_all_profiles():             return _indexer.get_all_profiles()
def delete_profile(aadhar):         _indexer.delete_profile(aadhar)
def update_profile(aadhar, data):   _indexer.update_profile(aadhar, data)
def get_activity_report(aadhar, limit=50, days_ago=None):
    return _indexer.get_activity_report(aadhar, limit, days_ago)
def augment_identity(aadhar, emb):  _indexer.augment_identity(aadhar, emb)
def delete_camera(cid):             _indexer.delete_camera(cid)
def register_camera_metadata(cid, locs, source=None): _indexer.register_camera_metadata(cid, locs, source)

# Legacy aliases
faiss_index   = property(lambda _: _indexer._faiss_index)
faiss_mapping = property(lambda _: _indexer._faiss_mapping)

import threading # Needed for rebuild_index_background shim
