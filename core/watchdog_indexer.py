import os
import cv2
import pickle
import numpy as np
import faiss
from core.ai_processor import face_app

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
IDENTITIES_FILE = os.path.join(DATA_DIR, "identities.pkl")

# Define FAISS Index in memory globally for quick access
faiss_index = None
faiss_mapping = []  # List mapping index integer to Aadhar string

def load_identities():
    """Loads the (embedding, aadhar_num) list from local disk."""
    if not os.path.exists(IDENTITIES_FILE):
        return []
    with open(IDENTITIES_FILE, "rb") as f:
        try:
            return pickle.load(f)
        except Exception:
            return []

def save_identities(identities):
    """Saves the tuple list natively to disk."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    with open(IDENTITIES_FILE, "wb") as f:
        pickle.dump(identities, f)

def update_faiss_index():
    """Rebuilds the FAISS index from the on-disk identities list using Cosine Similarity."""
    global faiss_index, faiss_mapping
    
    identities = load_identities()
    if not identities:
        faiss_index = None
        faiss_mapping = []
        return
        
    embeddings = []
    faiss_mapping = []
    
    for item in identities:
        if len(item) == 2:
            emb, aadhar = item
            name = "Unknown"
        else:
            emb, aadhar, name = item
            
        # Normalize the embedding to unit length for Cosine Similarity (IndexFlatIP)
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
            
        embeddings.append(emb)
        faiss_mapping.append({"aadhar": aadhar, "name": name})
        
    # Convert list of 1D arrays to 2D numpy matrix of float32
    embeddings_matrix = np.array(embeddings).astype('float32')
    
    dimension = 512 
    # Use IndexFlatIP (Inner Product) for Cosine Similarity on normalized vectors
    faiss_index = faiss.IndexFlatIP(dimension)
    faiss_index.add(embeddings_matrix)
    print(f"FAISS: Loaded {len(identities)} identities into IndexFlatIP (Cosine Similarity).")

def enroll_face(image_path: str, aadhar_num: str, name: str):
    """
    Reads an image, passes to InsightFace to extract the 512-d embedding.
    Throws Exception if no face is found. Otherwise binds and saves to Faiss.
    """
    if not os.path.exists(image_path):
        raise ValueError(f"Image frame does not exist at {image_path}")
        
    frame = cv2.imread(image_path)
    if frame is None:
        raise ValueError("Could not decode image.")
        
    # Process through InsightFace
    faces = face_app.get(frame)
    if not faces:
        raise ValueError("No faces detected in the image.")
    if len(faces) > 1:
        raise ValueError("Multiple faces detected! Please use an image with only one face.")
        
    face = faces[0]
    embedding = face.embedding
    
    # Store natively in repository
    identities = load_identities()
    identities.append((embedding, aadhar_num, name))
    save_identities(identities)
    
    # Update fast retrieval Faiss graph
    update_faiss_index()
    print(f"FAISS: Enrolled new identity: {name}")

def recognize_face(frame_embedding: np.ndarray, threshold: float = 0.45):
    """
    Queries the FAISS index for the closest match using Cosine Similarity.
    Threshold for Cosine Similarity is typically > 0.4 for ArcFace.
    """
    global faiss_index, faiss_mapping
    
    if faiss_index is None or faiss_index.ntotal == 0:
        return None
        
    # Normalize query vector
    norm = np.linalg.norm(frame_embedding)
    if norm > 0:
        frame_embedding = frame_embedding / norm
        
    # Ensure shape is (1, 512) and type float32 for FAISS
    query = np.array([frame_embedding]).astype('float32')
    similarities, indices = faiss_index.search(query, k=1)
    
    if len(similarities) > 0 and len(indices) > 0:
        match_idx = indices[0][0]
        match_sim = similarities[0][0] # In IndexFlatIP, this is the dot product (cosine)
        
        if match_idx != -1:
            if match_sim > threshold:
                res = faiss_mapping[match_idx]
                print(f"FAISS: Match found: {res['name']} (sim: {match_sim:.4f})")
                return res
            else:
                # Debug: Show close matches that missed the threshold
                if match_idx < len(faiss_mapping):
                    print(f"FAISS: Potential match {faiss_mapping[match_idx]['name']} ignored (sim: {match_sim:.4f} < {threshold})")
            
    return None

# initialize at boot
update_faiss_index()

# initialize at boot
update_faiss_index()
