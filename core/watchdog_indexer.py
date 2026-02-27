import os
import cv2
import pickle
import numpy as np
import faiss
import base64
from core.ai_processor import face_app # Kept this as it's used later
from datetime import datetime, timedelta
from core.database import get_sync_db

# MongoDB Handles (Sync for FAISS management)
db = get_sync_db()
profiles_col = db["profiles"] if db is not None else None
cameras_col = db["cameras"] if db is not None else None
activity_logs_col = db["activity_logs"] if db is not None else None

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
IDENTITIES_FILE = os.path.join(DATA_DIR, "identities.pkl")

# Define FAISS Index in memory globally for quick access
faiss_index = None
faiss_mapping = []  # List mapping index integer to meta dict

def migrate_pickle_to_mongo():
    """One-time migration from identities.pkl to MongoDB."""
    if os.path.exists(IDENTITIES_FILE):
        print("MongoDB: Found legacy identities.pkl. Migrating...")
        try:
            with open(IDENTITIES_FILE, "rb") as f:
                identities = pickle.load(f)
            
            for item in identities:
                if len(item) == 2:
                    emb, aadhar = item
                    name, threat = "Unknown", "Low"
                elif len(item) == 3:
                    emb, aadhar, name = item
                    threat = "Low"
                else:
                    emb, aadhar, name, threat = item
                
                # Upsert into MongoDB
                profiles_col.update_one(
                    {"aadhar": aadhar},
                    {"$set": {
                        "name": name,
                        "threat_level": threat,
                        "embedding": emb.tobytes() # Store as binary
                    }},
                    upsert=True
                )
            # Rename file to avoid repeated migration
            os.rename(IDENTITIES_FILE, IDENTITIES_FILE + ".bak")
            print(f"MongoDB: Migration complete. {len(identities)} profiles moved.")
        except Exception as e:
            print(f"MongoDB: Migration error: {e}")

def update_faiss_index():
    """Rebuilds the FAISS index from MongoDB collection with failure fallbacks."""
    global faiss_index, faiss_mapping
    
    # Run migration check
    migrate_pickle_to_mongo()
    
    if db is None:
        print("FAISS Error: MongoDB unreachable. Cannot rebuild index.")
        return

    try:
        cursor = profiles_col.find({})
        identities = list(cursor)
    except Exception as e:
        print(f"FAISS: Database query error: {e}")
        return
    
    if not identities:
        faiss_index = None
        faiss_mapping = []
        return
        
    embeddings = []
    faiss_mapping = []
    
    for doc in identities:
        # Convert binary back to numpy
        emb = np.frombuffer(doc["embedding"], dtype='float32')
        name = doc.get("name", "Unknown")
        threat = doc.get("threat_level", "Low")
        aadhar = doc.get("aadhar", "Unknown")
        phone = doc.get("phone", "N/A")
        address = doc.get("address", "N/A")
            
        # Normalize for Cosine Similarity
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
            
        embeddings.append(emb)
        faiss_mapping.append({
            "aadhar": aadhar, 
            "name": name, 
            "threat_level": threat,
            "phone": phone,
            "address": address,
            "photo_thumb": doc.get("photo_thumb", "")
        })
        
    embeddings_matrix = np.array(embeddings).astype('float32')
    faiss_index = faiss.IndexFlatIP(512)
    faiss_index.add(embeddings_matrix)
    print(f"FAISS: Loaded {len(identities)} identities from MongoDB with full meta-data.")

def enroll_face(image_path: str, aadhar_num: str, name: str, threat_level: str = "Low", phone: str = "", address: str = ""):
    """Extracts embedding and saves to MongoDB with full biometric profile."""
    if not os.path.exists(image_path):
        raise ValueError(f"Image frame does not exist at {image_path}")
        
    frame = cv2.imread(image_path)
    if frame is None:
        raise ValueError("Could not decode image.")
        
    faces = face_app.get(frame)
    if not faces:
        raise ValueError("No faces detected.")
    if len(faces) > 1:
        raise ValueError("Multiple faces detected in enrollment image.")
        
    face = faces[0]
    embedding = face.embedding
    
    # Generate Facial Thumbnail
    try:
        bbox = face.bbox.astype(int)
        # Add a 20% margin
        h, w, _ = frame.shape
        margin_x = int((bbox[2] - bbox[0]) * 0.2)
        margin_y = int((bbox[3] - bbox[1]) * 0.2)
        
        y1, y2 = max(0, bbox[1] - margin_y), min(h, bbox[3] + margin_y)
        x1, x2 = max(0, bbox[0] - margin_x), min(w, bbox[2] + margin_x)
        
        face_img = frame[y1:y2, x1:x2]
        face_img = cv2.resize(face_img, (160, 160))
        _, buffer = cv2.imencode('.jpg', face_img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        thumb_b64 = base64.b64encode(buffer).decode('utf-8')
    except Exception as e:
        print(f"Watchdog: Thumbnail generation failed - {e}")
        thumb_b64 = ""

    # Save to MongoDB
    profiles_col.update_one(
        {"aadhar": aadhar_num},
        {"$set": {
            "name": name,
            "threat_level": threat_level,
            "phone": phone,
            "address": address,
            "embedding": embedding.tobytes(),
            "photo_thumb": thumb_b64
        }},
        upsert=True
    )
    
    update_faiss_index()
    print(f"FAISS: Enrolled {name} with thumbnail into Long-Term Memory.")

def recognize_face(frame_embedding: np.ndarray, threshold: float = 0.45):
    """Queries the FAISS index for the closest match."""
    global faiss_index, faiss_mapping
    
    if faiss_index is None or faiss_index.ntotal == 0:
        return None
        
    norm = np.linalg.norm(frame_embedding)
    if norm > 0:
        frame_embedding = frame_embedding / norm
        
    query = np.array([frame_embedding]).astype('float32')
    similarities, indices = faiss_index.search(query, k=1)
    
    if len(similarities) > 0 and len(indices) > 0:
        match_idx = indices[0][0]
        match_sim = similarities[0][0]
        
        if match_idx != -1 and match_sim > threshold:
            res = faiss_mapping[match_idx]
            return res
            
    return None

def get_all_profiles():
    """Fetches all registered profiles from MongoDB."""
    if db is None: return []
    try:
        return list(profiles_col.find({}))
    except:
        return []

def delete_profile(aadhar: str):
    """Deletes a profile and rebuilds the index."""
    if db is None: return
    profiles_col.delete_one({"aadhar": aadhar})
    update_faiss_index()
    print(f"MongoDB: Deleted profile {aadhar}")

def update_profile(aadhar: str, update_data: dict):
    """Updates profile metadata and rebuilds the index."""
    if db is None: return
    profiles_col.update_one({"aadhar": aadhar}, {"$set": update_data})
    update_faiss_index()
    print(f"MongoDB: Updated profile {aadhar}")

def log_activity(aadhar: str, client_id: str):
    """Records a timestamped activity log for a known person with camera location metadata."""
    if activity_logs_col is None: return
    
    # Get camera locations
    cam = cameras_col.find_one({"client_id": client_id})
    locations = cam.get("locations", ["Unknown", "Unknown"]) if cam else ["Unknown", "Unknown"]
    
    log_entry = {
        "aadhar": aadhar,
        "client_id": client_id,
        "locations": locations,
        "timestamp": datetime.now(),
        "date_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    try:
        activity_logs_col.insert_one(log_entry)
        print(f"Watchdog: Logged activity for {aadhar} at {client_id} ({locations})")
    except Exception as e:
        print(f"Watchdog: Logging failed - {e}")

def register_camera_metadata(client_id: str, locations: list):
    """Assigns specific location metadata to a camera device."""
    if cameras_col is None: return
    cameras_col.update_one(
        {"client_id": client_id},
        {"$set": {"locations": locations[:2]}}, # Ensure only 2 locations
        upsert=True
    )
    print(f"MongoDB: Registered locations {locations} for camera {client_id}")

def get_activity_report(aadhar: str, limit: int = 50, days_ago: int = None):
    """Fetches chronological activity logs for a specific person.
    If days_ago is specified, filters logs from that many days ago until now.
    """
    if activity_logs_col is None: return []
    try:
        query = {"aadhar": aadhar}
        if days_ago is not None:
            # Calculate the threshold timestamp
            threshold_date = datetime.now() - timedelta(days=days_ago)
            threshold_timestamp = threshold_date.timestamp()
            query["timestamp"] = {"$gte": threshold_timestamp}
            
        cursor = activity_logs_col.find(query).sort("timestamp", -1).limit(limit)
        return list(cursor)
    except Exception as e:
        print(f"Watchdog: Report generation failed - {e}")
        return []

# Initial load
update_faiss_index()

