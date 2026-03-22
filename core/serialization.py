import msgpack
import msgpack_numpy as m
import numpy as np
import traceback

def pack(obj):
    """
    Packs data into msgpack format, handling numpy arrays and Face objects.
    """
    return msgpack.packb(_to_serializable(obj), default=m.encode)

def unpack(data):
    """
    Unpacks msgpack data.
    """
    if data is None:
        return None
    try:
        return msgpack.unpackb(data, object_hook=m.decode)
    except msgpack.ExtraData as e:
        print(f"Serialization Warning: Extra data found in buffer (len={len(data)}).")
        # Try to unpack just the first object if possible
        try:
            unpacker = msgpack.Unpacker(raw=False, object_hook=m.decode)
            unpacker.feed(data)
            return next(unpacker)
        except Exception as e2:
            print(f"Failed to recover first object from extra data: {e2}")
            return None
    except Exception as e:
        print(f"Serialization Error (unpack) [len={len(data)}]: {e}")
        # traceback.print_exc()
        return None

def _to_serializable(obj):
    """
    Recursively convert non-serializable objects (like insightface.Face) to dicts.
    """
    if obj is None:
        return None
        
    # Special handling for insightface.Face (check this BEFORE generic dict)
    if hasattr(obj, '__class__') and obj.__class__.__name__ == 'Face':
        res = {}
        # If it's a dict subclass, start with its items
        if isinstance(obj, dict):
            for k, v in obj.items():
                res[k] = _to_serializable(v)
        
        # Explicitly collect standard Face attributes if not already in res
        for attr in ['embedding', 'normed_embedding', 'sex', 'age', 'pose', 'ident_meta', 'bbox', 'kps', 'det_score', 'norm']:
            if hasattr(obj, attr):
                val = getattr(obj, attr)
                if val is not None and attr not in res:
                    res[attr] = _to_serializable(val)
        return res

    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_to_serializable(i) for i in obj]
    elif isinstance(obj, (np.ndarray, np.generic)):
        # Let msgpack-numpy handle these
        return obj
    elif isinstance(obj, (tuple, set)):
        return [_to_serializable(i) for i in obj]
        
    return obj
