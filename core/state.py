from collections import deque

# Thread-safe queue: maxlen=2 keeps only the latest frames, discarding stale ones
frame_queue = deque(maxlen=2)
