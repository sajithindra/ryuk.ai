import sys
import os
import numpy as np
import faiss

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.watchdog_indexer import WatchdogIndexer

def verify():
    print("FAISS GPU Verification Script")
    print("-" * 30)
    
    try:
        indexer = WatchdogIndexer()
        index = indexer._faiss_index
        
        if index is None:
            print("FAISS Index is None (probably no identities in DB).")
            # Create a mock index for testing
            print("Creating a mock index for testing...")
            res = faiss.StandardGpuResources()
            cpu_idx = faiss.IndexFlatIP(512)
            gpu_idx = faiss.index_cpu_to_gpu(res, 0, cpu_idx)
            index = gpu_idx
            
        print(f"Index type: {type(index)}")
        
        # Check if it's a GPU index
        is_gpu = "GpuIndex" in str(type(index)) or isinstance(index, faiss.GpuIndexFlat)
        if is_gpu:
            print("SUCCESS: FAISS Index is on GPU.")
        else:
            print("FAILURE: FAISS Index is NOT on GPU.")
            return
            
        # Test adding and searching
        print("Testing add and search...")
        mock_embedding = np.random.random((1, 512)).astype("float32")
        faiss.normalize_L2(mock_embedding)
        index.add(mock_embedding)
        print(f"Index now has {index.ntotal} vectors.")
        
        sims, idxs = index.search(mock_embedding, k=1)
        print(f"Search results: scores={sims}, indices={idxs}")
        
        if idxs[0][0] != -1:
            print("SUCCESS: Search verified.")
        else:
            print("FAILURE: Search failed.")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify()
