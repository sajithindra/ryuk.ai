import warnings
import os
import numpy as np
import onnxruntime as ort

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
    "trt_max_workspace_size":      3 * 1024 * 1024 * 1024,  # 3 GB
    "trt_builder_optimization_level": 5,                    # max fusion
    "trt_timing_cache_enable":     True,                    # reuse timing across sessions
    "trt_timing_cache_path":       _TRT_CACHE,
    "trt_auxiliary_streams":       4,                       # parallel streams for small ops
    "trt_dump_ep_context_model":   False,
}

_cuda_options = {
    "device_id":                   0,
    "gpu_mem_limit":               5 * 1024 * 1024 * 1024,  # 5 GB
    "arena_extend_strategy":       "kNextPowerOfTwo",
    "cudnn_conv_algo_search":      "EXHAUSTIVE",
    "do_copy_in_default_stream":   True,
    "enable_cuda_graph":           True,
}

providers = []
if "TensorrtExecutionProvider" in _available:
    providers.append(("TensorrtExecutionProvider", _trt_options))
if "CUDAExecutionProvider" in _available:
    providers.append(("CUDAExecutionProvider", _cuda_options))
providers.append("CPUExecutionProvider")

face_app = FaceAnalysis(name='buffalo_l', providers=providers)
face_app.prepare(ctx_id=0, det_size=(640, 640))

# Report active providers for each model
for model_name, model in face_app.models.items():
    active = model.session.get_providers()
    is_trt  = "TensorrtExecutionProvider" in active
    is_cuda = "CUDAExecutionProvider" in active
    status  = "[TRT ✓]" if is_trt else ("[CUDA ✓]" if is_cuda else "[CPU ⚠]")
    print(f"  {status} {model.taskname}")

print("InsightFace GPU initialization complete.")

def warmup():
    """Run a dummy inference to pre-allocate GPU memory and tune cuDNN kernels."""
    print("GPU Warmup: Running dummy inference to eliminate initial lag...")
    dummy_frame = np.zeros((640, 640, 3), dtype=np.uint8)
    # The first call triggers TRT/cuDNN kernel selection and memory allocation
    face_app.get(dummy_frame)
    print("GPU Warmup: Complete. Application is ready for instant streaming.")

warmup()
