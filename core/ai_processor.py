import warnings
import os
import numpy as np
import onnxruntime as ort
import ctypes.util
import threading

warnings.filterwarnings("ignore", category=FutureWarning, module="insightface")
warnings.filterwarnings("ignore", category=FutureWarning, module="skimage")

from insightface.app import FaceAnalysis

print("Initializing InsightFace model...")
_available = ort.get_available_providers()
print(f"  ORT {ort.__version__} | Providers: {_available}")

# =============================================================================
# PROVIDER CONFIGURATION — RTX 3070 Ti (8 GB VRAM), cuDNN 9.19.1, ORT 1.24.2
#
# Priority:  TensorrtExecutionProvider  ← fastest (Tensor Cores, fused ops)
#            CUDAExecutionProvider       ← fallback for ops TRT doesn't support
#            CPUExecutionProvider        ← last resort
# =============================================================================

_TRT_CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "trt_cache")
os.makedirs(_TRT_CACHE, exist_ok=True)

_trt_options = {
    "device_id":                   0,
    "trt_fp16_enable":             True,
    "trt_engine_cache_enable":     True,
    "trt_engine_cache_path":       _TRT_CACHE,
    "trt_max_workspace_size":      2 * 1024 * 1024 * 1024,  # 2 GB for 3070 Ti
    "trt_builder_optimization_level": 5,
    "trt_timing_cache_enable":     True,
    "trt_timing_cache_path":       _TRT_CACHE,
    "trt_detailed_build_log":      False,
}

_cuda_options = {
    "device_id":                   0,
    "gpu_mem_limit":               4 * 1024 * 1024 * 1024,  # 4 GB limit
    "arena_extend_strategy":       "kSameAsRequested",
    "cudnn_conv_algo_search":      "DEFAULT",
    "do_copy_in_default_stream":   True,
}

providers = []
# Force try TRT and CUDA if they show up in available
if "TensorrtExecutionProvider" in _available:
    # We append it even if find_library fails, as ORT sometimes finds it on its own path
    providers.append(("TensorrtExecutionProvider", _trt_options))
if "CUDAExecutionProvider" in _available:
    providers.append(("CUDAExecutionProvider", _cuda_options))
providers.append("CPUExecutionProvider")

# Use 640x640 for better accuracy and to give the GPU meaningful work
DET_SIZE = (640, 640)
face_app = FaceAnalysis(name='buffalo_l', providers=providers)
face_app.prepare(ctx_id=0, det_size=DET_SIZE)

# =============================================================================
# IO BINDING — Fast "Tensor.cuda()" style data flow
# =============================================================================
class IOBindingWrapper:
    """Zero-copy (or minimized copy) wrapper for ONNX Runtime sessions."""
    def __init__(self, model):
        self.model = model
        self.session = model.session
        self.io_binding = self.session.io_binding()
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        
        # Pre-bind outputs to CUDA to avoid re-allocation
        for name in self.output_names:
            self.io_binding.bind_output(name, 'cuda', 0)

    def run_optimized(self, blob):
        # blob: (1, 3, 640, 640) float32
        # Bind input (this is the "tensor.cuda()" equivalent in pure ORT)
        self.io_binding.bind_cpu_input(self.input_name, blob)
        self.session.run_with_iobinding(self.io_binding)
        return self.io_binding.copy_outputs_to_cpu()

# Inference Lock for Global Thread-Safety (Multiple process instances)
_inf_lock = threading.Lock()

# Apply IO Binding to the detection model (the most intensive part)
try:
    det_model = face_app.models['detection']
    det_wrapper = IOBindingWrapper(det_model)
    
    # Monkey-patch the internal run to use our optimized path
    # RetinaFace.forward or similar usually calls session.run
    # We'll override the session's run method for this instance specifically
    original_run = det_model.session.run
    def fast_run(output_names, input_feed, run_options=None):
        if det_wrapper.input_name in input_feed:
            with _inf_lock:
                return det_wrapper.run_optimized(input_feed[det_wrapper.input_name])
        return original_run(output_names, input_feed, run_options)
        
    det_model.session.run = fast_run
    print("  [IO BINDING ✓] Enabled for Detection Model")
except Exception as e:
    print(f"  [IO BINDING ⚠] Failed to enable: {e}")

# Report active providers for each model
for model_name, model in face_app.models.items():
    active = model.session.get_providers()
    is_trt  = "TensorrtExecutionProvider" in active
    is_cuda = "CUDAExecutionProvider" in active
    status  = "[TRT ✓]" if is_trt else ("[CUDA ✓]" if is_cuda else "[CPU ⚠]")
    print(f"  {status} {model.taskname} on {active}")

print(f"InsightFace GPU initialization complete. Target resolution: {DET_SIZE}")

# =============================================================================
# GPU WARMUP — Trigger TensorRT Engine building and "Wake up" GPU cores
# =============================================================================
try:
    print("\nStarting GPU Warmup (50 cycles)...")
    import time
    dummy_frame = np.zeros((*DET_SIZE, 3), dtype=np.uint8)
    
    start_warmup = time.time()
    for i in range(50):
        _ = face_app.get(dummy_frame)
        if i % 10 == 0:
            print(f"  Warmup cycle {i}...")
    
    warmup_duration = time.time() - start_warmup
    print(f"GPU Warmup Complete in {warmup_duration:.2f}s. GPU is now active.")
except Exception as e:
    print(f"GPU Warmup Failed: {e}")
