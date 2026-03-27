#!/bin/bash
# Ryuk AI Dashboard Launcher
# This script ensures the correct virtual environment and GPU library paths are loaded.

# 1. Resolve Project Root
PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$PROJECT_ROOT"

# 2. Configure Environment (Dynamic Library Path Discovery)
# This finds CUDA, cuDNN, and TensorRT libraries bundled in the .venv
if [ -d "./.venv" ]; then
    VENV_SITE_PACKAGES="./.venv/lib/python3.12/site-packages"
    
    # Identify directories containing .so files for Nvidia and TensorRT
    LIB_PATHS=$(find "$VENV_SITE_PACKAGES" -maxdepth 3 -type d \( -name "lib" -o -name "tensorrt_libs" \) | tr '\n' ':')
    
    # Prepend to LD_LIBRARY_PATH
    export LD_LIBRARY_PATH="$LIB_PATHS$LD_LIBRARY_PATH"
    
    # Debug info (optional)
    # echo "[*] Configured LD_LIBRARY_PATH with venv libraries."
fi

# 3. Launch with VENV Python
if [ -f "./.venv/bin/python3" ]; then
    echo "[*] Launching Ryuk AI via .venv..."
    ./.venv/bin/python3 main.py
else
    echo "[!] Error: .venv not found at $PROJECT_ROOT/.venv"
    echo "Please ensure the virtual environment is correctly set up."
    exit 1
fi
