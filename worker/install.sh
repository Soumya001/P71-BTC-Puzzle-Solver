#!/bin/bash
# Bitcoin Puzzle Pool Worker Setup Script
# Usage: bash install.sh <POOL_URL> [WORKER_NAME]

set -e

POOL_URL="${1:?Usage: bash install.sh <POOL_URL> [WORKER_NAME]}"
WORKER_NAME="${2:-worker-$(hostname)}"

echo "=== Bitcoin Puzzle Pool Worker Setup ==="
echo "Pool URL: $POOL_URL"
echo "Worker Name: $WORKER_NAME"
echo ""

# Check for NVIDIA GPU
echo "[1/4] Checking for NVIDIA GPU..."
if ! command -v nvidia-smi &> /dev/null; then
    echo "ERROR: nvidia-smi not found. Install NVIDIA drivers first."
    exit 1
fi

nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo ""

# Check for CUDA
echo "[2/4] Checking for CUDA..."
if ! command -v nvcc &> /dev/null; then
    echo "WARNING: nvcc not found. CUDA toolkit may not be installed."
    echo "KeyHunt-Cuda may still work if CUDA runtime libraries are present."
else
    nvcc --version | head -4
fi
echo ""

# Check for KeyHunt-Cuda
echo "[3/4] Checking for KeyHunt-Cuda..."
KEYHUNT_PATH=""
for path in /usr/local/bin/KeyHunt ./KeyHunt ~/KeyHunt-Cuda/KeyHunt; do
    if [ -x "$path" ]; then
        KEYHUNT_PATH="$path"
        break
    fi
done

if [ -z "$KEYHUNT_PATH" ]; then
    echo "KeyHunt-Cuda binary not found."
    echo "Please build or download KeyHunt-Cuda and place it in your PATH."
    echo "Build instructions: https://github.com/albertobsd/keyhunt"
    echo ""
    echo "After building, run this script again or start the worker manually:"
    echo "  python3 worker.py --pool-url $POOL_URL --name $WORKER_NAME --keyhunt-path /path/to/KeyHunt"
    exit 1
fi

echo "Found KeyHunt at: $KEYHUNT_PATH"
echo ""

# Install Python dependencies
echo "[4/4] Installing Python dependencies..."
pip3 install --user requests 2>/dev/null || pip install --user requests

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Start the worker with:"
echo "  python3 worker.py --pool-url $POOL_URL --name $WORKER_NAME --keyhunt-path $KEYHUNT_PATH"
echo ""
echo "Or run in background:"
echo "  nohup python3 worker.py --pool-url $POOL_URL --name $WORKER_NAME --keyhunt-path $KEYHUNT_PATH > worker.log 2>&1 &"
