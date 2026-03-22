import os
import sys

def debug_paths():
    root = os.getcwd()
    venv_site = os.path.join(root, ".venv", "lib", "python3.12", "site-packages")
    nvidia_root = os.path.join(venv_site, "nvidia")
    
    print(f"Checking nvidia_root: {nvidia_root}")
    if os.path.isdir(nvidia_root):
        for sub in os.listdir(nvidia_root):
            lib_path = os.path.join(nvidia_root, sub, "lib")
            if os.path.isdir(lib_path):
                print(f"Found lib: {lib_path}")
                for f in os.listdir(lib_path):
                    if "nvJitLink" in f or "cusparse" in f:
                        print(f"  - {f}")
    else:
        print("NVIDIA root not found!")

if __name__ == "__main__":
    debug_paths()
