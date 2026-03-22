import redis

cache = redis.Redis(host='localhost', port=6379, db=0, decode_responses=False)

queues = ["ryuk:detect", "ryuk:embed", "ryuk:faiss"]
for q in queues:
    length = cache.llen(q)
    if length > 0:
        print(f"Clearing queue '{q}' ({length} items)...")
        cache.delete(q)
    else:
        print(f"Queue '{q}' is already empty.")

print("All queues cleared!")
