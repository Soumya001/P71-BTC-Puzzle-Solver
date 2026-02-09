# Bitcoin Puzzle #71 — Pool Worker

Join the hunt for Bitcoin Puzzle #71. Download the worker, point it at your GPU, and start scanning with the pool. Zero duplicate work, live stats, modern GUI.

**Dashboard:** [starnetlive.space](https://starnetlive.space)

## Download

Grab the latest binary from [**Releases**](https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases):

| Platform | File | How to Run |
|----------|------|------------|
| Windows  | `puzzle-worker.exe` | Double-click |
| Linux    | `puzzle-worker-linux` | `chmod +x puzzle-worker-linux && ./puzzle-worker-linux` |

## Requirements

- **NVIDIA GPU** with CUDA drivers installed
- **[KeyHunt-Cuda](https://github.com/albertobsd/keyhunt)** — the scanning engine

### Installing KeyHunt-Cuda

**Linux:**
```bash
git clone https://github.com/albertobsd/keyhunt.git
cd keyhunt
make gpu=1
```

**Windows:** Download a pre-built release from the KeyHunt-Cuda repo or build with Visual Studio.

## Quick Start

1. Download `puzzle-worker.exe` (Windows) or `puzzle-worker-linux` (Linux)
2. Run it — a setup window will ask for:
   - **Pool URL** — leave default (`https://starnetlive.space`)
   - **Worker Name** — pick any name
   - **KeyHunt Path** — point to your KeyHunt-Cuda binary
   - **GPU ID** — usually `0`
3. Click **START MINING**
4. Watch your GPU scan billions of keys per second

## What You'll See

The worker GUI shows:
- **Current scan** — chunk ID, key range, progress bar
- **Canary verification** — anti-cheat proof-of-work indicators
- **Your stats** — chunks completed, keys scanned, speed, uptime
- **System stats** — GPU usage/temp/power, VRAM, CPU, RAM
- **Pool stats** — active workers, total pool speed, ETA, overall progress

## Command Line Options

```
puzzle-worker --no-gui          # Plain text mode (no window)
puzzle-worker --auto            # Use saved config, skip setup
puzzle-worker --pool-url URL    # Custom pool URL
puzzle-worker --name MyWorker   # Set worker name
puzzle-worker --keyhunt-path /path/to/KeyHunt
puzzle-worker --gpu-id 1        # Use second GPU
```

## How It Works

- The pool server splits Puzzle #71's keyspace (2^70 keys) into chunks of 2^36 keys
- Your worker gets a batch of 4 chunks at a time
- KeyHunt-Cuda scans each chunk using your GPU
- Results are reported back with canary proofs (anti-cheat)
- No key is ever stored on your machine — only the server holds found keys
- If the key is found, rewards are distributed to contributors

## Run from Source (Alternative)

```bash
pip install customtkinter
python puzzle_worker.py
```

## FAQ

**Is this safe?** The worker only runs KeyHunt-Cuda (open source) on your GPU and reports results to the pool. No keys are stored locally.

**What GPU do I need?** Any NVIDIA GPU with CUDA support. GTX 1060+ recommended.

**Can I run multiple GPUs?** Run one worker instance per GPU with different `--gpu-id` values.

**What happens if the key is found?** The pool server securely stores the key. Rewards are distributed to contributing workers.
