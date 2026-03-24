#!/bin/bash
# Ryuk AI Dashboard Launcher
# This script ensures the correct virtual environment and GPU library paths are loaded.

# 1. Resolve Project Root
PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$PROJECT_ROOT"

# 2. Configure Environment
# 2. Configure Environment (Persistent paths from .venv)
VENV_SITE="$PROJECT_ROOT/.venv/lib/python3.12/site-packages"
ONNX_LIB="$VENV_SITE/onnxruntime/capi"
NVIDIA_LIBS=""
if [ -d "$VENV_SITE/nvidia" ]; then
    for dir in "$VENV_SITE"/nvidia/*/lib; do
        if [ -d "$dir" ]; then
            NVIDIA_LIBS="$NVIDIA_LIBS:$dir"
        fi
    done
fi
export LD_LIBRARY_PATH="$ONNX_LIB$NVIDIA_LIBS:$LD_LIBRARY_PATH"


# 3. Pre-flight Cleanup
# Ensure no zombie processes are holding onto ports 8000 or 8001
echo "[*] Cleaning up existing Ryuk processes..."
fuser -k 8000/tcp 8001/tcp > /dev/null 2>&1
pkill -f "python3 main.py" > /dev/null 2>&1
pkill -f "python3 manager.py" > /dev/null 2>&1
pkill -f "unified_engine.py" > /dev/null 2>&1
pkill -f "alpr_service.py" > /dev/null 2>&1
pkill -f "sink.py" > /dev/null 2>&1
sleep 1

# 4. Launch with VENV Python
if [ -f "./.venv/bin/python3" ]; then
    echo "[*] Launching Ryuk AI via .venv..."
    ./.venv/bin/python3 main.py
else
    echo "[!] Error: .venv not found at $PROJECT_ROOT/.venv"
    echo "Please ensure the virtual environment is correctly set up."
    exit 1
fi

# 5. Restore Terminal State
# Ensures shell history and cursor behavior are restored after Ctrl+C
stty sane
echo "[*] Ryuk AI Session Ended."
