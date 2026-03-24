#!/bin/bash
# Ryuk AI Dashboard Launcher
# This script ensures the correct virtual environment and GPU library paths are loaded.

# 1. Resolve Project Root
PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$PROJECT_ROOT"

# 2. Configure Environment
export LD_LIBRARY_PATH="/tmp/pip-install-5_vpsqas/onnxruntime-gpu_f68a5293444445889601f016599b4d00/onnxruntime/capi/lib:$LD_LIBRARY_PATH"

# 3. Launch with VENV Python
if [ -f "./.venv/bin/python3" ]; then
    echo "[*] Launching Ryuk AI via .venv..."
    ./.venv/bin/python3 main.py
else
    echo "[!] Error: .venv not found at $PROJECT_ROOT/.venv"
    echo "Please ensure the virtual environment is correctly set up."
    exit 1
fi
