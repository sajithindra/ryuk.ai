import os
import sys

def bootstrap_gpu():
    """
    Ensures that GPU-related libraries (CUDA, cuDNN, TensorRT) in the virtual environment
    are correctly added to LD_LIBRARY_PATH before any heavy imports are made.
    If the environment changes, it re-executes the script with the new environment.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Check if we are in a venv, otherwise locate it
    is_venv = hasattr(sys, 'real_prefix') or (sys.base_prefix != sys.prefix)
    venv_python = os.path.join(root, ".venv", "bin", "python3")
    target_exe = venv_python if (not is_venv and os.path.exists(venv_python)) else sys.executable

    # Build LD_LIBRARY_PATH additions from .venv/lib/pythonx.y/site-packages
    candidate_dirs = []
    
    # Find Python version for path
    py_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = os.path.join(root, ".venv", "lib", py_version, "site-packages")
    
    if os.path.isdir(site_packages):
        # 1. Standard Nvidia packages (cudnn, cublas, etc.)
        nvidia_root = os.path.join(site_packages, "nvidia")
        if os.path.isdir(nvidia_root):
            for sub in os.listdir(nvidia_root):
                lib_path = os.path.join(nvidia_root, sub, "lib")
                if os.path.isdir(lib_path):
                    candidate_dirs.append(lib_path)
        
        # 2. TensorRT libraries (often in tensorrt_libs)
        trt_libs = os.path.join(site_packages, "tensorrt_libs")
        if os.path.isdir(trt_libs):
            candidate_dirs.append(trt_libs)
            
        # 3. Any other direct site-packages directories containing .so files if needed
        # (Add more here if discovery shows other critical locations)

    # 4. Standard System Paths (Last)
    system_paths = ["/usr/lib/x86_64-linux-gnu", "/usr/local/cuda/lib64"]
    candidate_dirs.extend(system_paths)

    # Clean and check if update needed
    current_ld = os.environ.get("LD_LIBRARY_PATH", "")
    existing = set(current_ld.split(":")) if current_ld else set()
    additions = [d for d in candidate_dirs if os.path.isdir(d) and d not in existing]

    if (target_exe != sys.executable) or additions:
        if additions:
            new_ld = ":".join(additions) + ((":" + current_ld) if current_ld else "")
            os.environ["LD_LIBRARY_PATH"] = new_ld
            # print(f"[*] Bootstrapping environment: Added {len(additions)} paths to LD_LIBRARY_PATH")
        
        # Re-execute process
        os.execv(target_exe, [target_exe] + sys.argv)

if __name__ == "__main__":
    # Test call
    bootstrap_gpu()
    print("Bootstrap completed.")
