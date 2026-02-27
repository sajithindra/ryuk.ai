from insightface.app import FaceAnalysis

print("Initializing InsightFace model...")
# Explicitly set providers to prefer GPU (CUDAExecutionProvider) and fallback to CPU
providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
face_app = FaceAnalysis(name='buffalo_l', providers=providers)
face_app.prepare(ctx_id=0, det_size=(640, 640))
print("InsightFace model initialized successfully.")
