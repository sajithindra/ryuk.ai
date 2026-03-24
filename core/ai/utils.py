import numpy as np
import onnxruntime as ort
import torch
import torch.nn.functional as F
from core.logger import logger

class IOBindingWrapper:
    """Optimized ONNX Runtime IO Binding wrapper for GPU inference."""
    def __init__(self, model_or_session):
        if hasattr(model_or_session, 'session'):
            self.model = model_or_session
            self.session = model_or_session.session
        else:
            self.model = None
            self.session = model_or_session
        self.io_binding = self.session.io_binding()
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        for name in self.output_names:
            self.io_binding.bind_output(name, 'cuda', 0)

    def run_optimized(self, blob):
        if torch.is_tensor(blob):
            self.io_binding.bind_input(
                name=self.input_name,
                device_type='cuda',
                device_id=0,
                element_type=np.float32,
                shape=tuple(blob.shape),
                buffer_ptr=blob.data_ptr()
            )
        else:
            self.io_binding.bind_cpu_input(self.input_name, blob)
        
        self.session.run_with_iobinding(self.io_binding)
        return self.io_binding.copy_outputs_to_cpu()

class TorchFaceAligner:
    """High-performance GPU-based face alignment using spatial transformers."""
    def __init__(self, device='cuda'):
        self.device = device
        # Standard 112x112 reference points for InsightFace
        self.reference_pts = torch.tensor([
            [30.2946, 51.6963],
            [65.5318, 51.5014],
            [48.0252, 71.7366],
            [33.5493, 92.3655],
            [62.7299, 92.2041]
        ], dtype=torch.float32, device=device)
        self.reference_pts = (self.reference_pts / 112.0) * 2.0 - 1.0 # Norm to [-1, 1]
        self.output_size = (112, 112)

    def align_batched(self, frames_gpu, landmarks_gpu, frame_indices):
        """
        frames_gpu: (B, 3, H, W) on GPU
        landmarks_gpu: (N, 5, 2) on GPU
        frame_indices: (N,) tensor of frame indices in frames_gpu
        """
        N = landmarks_gpu.shape[0]
        if N == 0: return torch.empty((0, 3, 112, 112), device=self.device)
        
        H, W = frames_gpu.shape[2:]
        lms_norm = landmarks_gpu.clone()
        lms_norm[..., 0] = (lms_norm[..., 0] / W) * 2.0 - 1.0
        lms_norm[..., 1] = (lms_norm[..., 1] / H) * 2.0 - 1.0
        
        ones = torch.ones(N, 5, 1, device=self.device)
        ref_aug = torch.cat([self.reference_pts.unsqueeze(0).expand(N, -1, -1), ones], dim=2)
        M_T = torch.linalg.lstsq(ref_aug, lms_norm).solution
        M = M_T.transpose(1, 2)
        
        selected_frames = frames_gpu[frame_indices]
        grid = F.affine_grid(M, size=(N, 3, 112, 112), align_corners=False)
        chips = F.grid_sample(selected_frames, grid, align_corners=False, mode='bilinear', padding_mode='zeros')
        return chips

class TorchPreprocessor:
    """GPU-accelerated preprocessing for InsightFace detection models."""
    def __init__(self, target_size=(640, 640), device='cuda'):
        self.target_size = target_size
        self.device = device
        
    def preprocess_batched(self, frames_np_list):
        if not frames_np_list: return None
        batch_t = [torch.from_numpy(np.array(f, copy=True, order='C')).to(self.device).permute(2, 0, 1) for f in frames_np_list]
        resized = [F.interpolate(f.unsqueeze(0).float(), size=self.target_size, mode='bilinear', align_corners=False) for f in batch_t]
        batch_tensor = torch.cat(resized, dim=0)
        batch_tensor = batch_tensor[:, [2, 1, 0], :, :] # BGR to RGB
        batch_tensor = (batch_tensor - 127.5) / 128.0
        return batch_tensor
