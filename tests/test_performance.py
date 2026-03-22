import time
import numpy as np
import torch
from services.unified_engine import UnifiedInferenceEngine
from core.state import cache
import core.serialization as serde

def benchmark_engine(num_streams=4, num_frames=100):
    print(f"--- Benchmarking UnifiedInferenceEngine ({num_streams} streams, {num_frames} frames) ---")
    
    # Initialize engine
    engine = UnifiedInferenceEngine()
    
    # Prepare dummy frame
    frame = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
    
    # Simulate ingest queue
    start_time = time.time()
    for f in range(num_frames):
        for s in range(num_streams):
            packet = {
                "client_id": f"cam_{s}",
                "frame_count": f,
                "timestamp": time.time(),
                "frame": frame.copy()
            }
            cache.rpush("ryuk:ingest", serde.pack(packet))
    
    print(f"Pushed {num_streams * num_frames} frames to queue.")
    
    # Process frames
    processed = 0
    total_latency = 0
    
    engine_start = time.time()
    while processed < (num_streams * num_frames):
        packed = cache.blpop("ryuk:ingest", timeout=5)
        if not packed: break
        
        _, data = packed
        packet = serde.unpack(data)
        
        t0 = time.time()
        # Mocking the engine's internal call to ai_processor if we want pure pipeline test
        # Here we just run the engine's frame processing logic
        engine.process_frame(packet)
        t1 = time.time()
        
        processed += 1
        total_latency += (t1 - t0)
        
    engine_end = time.time()
    
    total_time = engine_end - engine_start
    avg_latency = (total_latency / processed) * 1000 if processed > 0 else 0
    fps = processed / total_time if total_time > 0 else 0
    
    print(f"\nResults:")
    print(f"Total processed: {processed}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Average Latency: {avg_latency:.2f}ms")
    print(f"Throughput: {fps:.2f} FPS")
    
    if torch.cuda.is_available():
        print(f"Peak GPU Memory: {torch.cuda.max_memory_allocated() / (1024**2):.2f} MB")

if __name__ == "__main__":
    benchmark_engine()
