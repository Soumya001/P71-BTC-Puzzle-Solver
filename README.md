<p align="center">
  <img src="BTC_Puzzle_Pool_Logo.svg" alt="BTC Puzzle Pool Logo" width="200"/>
</p>

<h1 align="center">Bitcoin Puzzle #71 — Pool Worker v4.2.0</h1>

<p align="center">
  <strong>Join the hunt for Bitcoin Puzzle #71. Download, run, mine. That's it.</strong>
</p>

<p align="center">
  <a href="https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases/latest"><img src="https://img.shields.io/github/v/release/Soumya001/P71-BTC-Puzzle-Solver?style=flat-square&color=f7931a" alt="Release"/></a>
  <a href="https://starnetlive.space"><img src="https://img.shields.io/badge/Dashboard-starnetlive.space-00e5ff?style=flat-square" alt="Dashboard"/></a>
  <a href="https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases"><img src="https://img.shields.io/github/downloads/Soumya001/P71-BTC-Puzzle-Solver/total?style=flat-square&color=00e676" alt="Downloads"/></a>
</p>

---

## What Is This?

The [Bitcoin Puzzle Transaction](https://privatekeys.pw/puzzles/bitcoin-puzzle-tx) is a series of unsolved cryptographic challenges where BTC is locked behind private keys in known address ranges. **Puzzle #71** has real BTC waiting to be found in a 2^70 keyspace.

This project is a **distributed pool** that splits the massive keyspace across many workers worldwide. Each worker scans a small chunk — together, we cover ground that no single machine could.

- **Pool server** coordinates work at [starnetlive.space](https://starnetlive.space)
- **This worker** runs on your machine and scans ranges assigned by the pool
- **KeyHunt-Cuda** is the GPU-accelerated scanning engine under the hood

## Download

Get the latest from [**Releases**](https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases/latest):

| Platform | File | How to Run |
|----------|------|------------|
| Windows  | `puzzle-worker.exe` | Double-click |
| Linux    | `puzzle-worker-linux` | `chmod +x puzzle-worker-linux && ./puzzle-worker-linux` |
| macOS    | `puzzle-worker-macos` | `chmod +x puzzle-worker-macos && ./puzzle-worker-macos` |

## Quick Start

1. Download and run the binary for your platform
2. It auto-creates `C:\PuzzlePool` (Windows) or `~/.puzzle-pool` (Linux/macOS)
3. Downloads the scanning engine automatically (first run only)
4. Creates a desktop shortcut
5. Connects to the pool and registers your worker
6. Press **Start** to begin scanning
7. Close the window — it keeps running in the system tray

**No setup. No configuration. No terminal commands.**

## Requirements

- **NVIDIA GPU** with CUDA drivers installed (for GPU mode)
- Internet connection (must stay connected to the pool)
- CPU-only mode available if you don't have an NVIDIA GPU

## Features

### v4.2.0 Highlights
- **Modern two-column UI** — stats and controls on the left, live log stream on the right
- **Dark/Light theme** — toggle with the moon/sun button, preference saved
- **Glass-like card design** — rounded corners, subtle borders, depth hierarchy
- **Animated progress bars** — smooth easing animation at ~60fps
- **ETA calculation** — estimated time remaining for current chunk
- **macOS support** — native builds for Apple Silicon and Intel Macs
- **New logo** — colorful puzzle-piece Bitcoin design

### Controls
- **Start / Pause / Stop** — full control over scanning
  - **Start** connects to the pool and begins scanning chunks
  - **Pause** finishes the current chunk, then waits until you resume
  - **Stop** immediately halts scanning and returns to idle

### Scan Modes
- **Normal** — continuous scanning, immediately requests next chunk after completing one
- **Eco** — adds a configurable cooldown (default 60s) between chunks to reduce heat and power usage

### Device Selection
- **GPU** — uses your NVIDIA GPU via CUDA (fastest, ~1 GKey/s on RTX 3060 Ti)
- **CPU** — uses CPU threads only (no GPU required)
- **CPU+GPU** — uses both simultaneously for maximum throughput

### Settings
Click the gear icon to configure:
- **Worker Name** — your worker's display name on the dashboard
- **GPU ID** — which GPU to use (0, 1, 2...) for multi-GPU systems
- **CPU Threads** — number of CPU threads (1-64) for CPU/CPU+GPU mode
- **Device Mode** — GPU / CPU / CPU+GPU
- **Scan Mode** — Normal / Eco
- **Eco Cooldown** — seconds to wait between chunks in Eco mode (10-300)

Settings are saved to `config.json` and persist across restarts.

### Live Monitoring
- Real-time speed, progress, and ETA for current chunk
- GPU temperature, power draw, VRAM usage
- CPU and RAM utilization
- Heartbeat status indicator
- Pool-wide statistics: active workers, total speed, overall progress
- System tray — mining continues in background when you close the window

## How It Works

### The Puzzle

Bitcoin Puzzle #71 has a known address with BTC locked behind a private key somewhere in a **2^70 keyspace** (~1.18 sextillion keys). The pool splits this into **2^30 chunks** (each chunk = **2^40 keys** = ~1.1 trillion keys). Workers scan chunks in parallel across the globe.

At 1 GKey/s per GPU, one chunk takes ~18 minutes. The full keyspace would take a single GPU over 37,000 years — but with hundreds of workers running simultaneously, we can cover it in a reasonable timeframe.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Pool Server                               │
│                 starnetlive.space                             │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │  Bitmap   │  │  SQLite  │  │  Stats   │  │   Gap    │    │
│  │  128 MB   │  │   DB     │  │  Engine  │  │ Scanner  │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
│                                                              │
│  REST API: /register, /work, /heartbeat, /complete, /stats  │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
   ┌────v────┐   ┌────v────┐   ┌────v────┐
   │Worker 1 │   │Worker 2 │   │Worker N │
   │ RTX3060 │   │ RTX4090 │   │  CPU    │
   │ 1 GK/s  │   │ 4 GK/s  │   │ 10MK/s │
   └─────────┘   └─────────┘   └─────────┘
```

### Work Flow

```
Worker                          Pool Server
  |                                |
  |── GET /api/register ──────────>│  Register worker, get API key
  |<── api_key ────────────────────│
  |                                |
  |── GET /api/work ──────────────>│  Request a chunk assignment
  |<── assignment_id, range, target│
  |                                |
  |   [Run KeyHunt on range]       |
  |                                |
  |── POST /api/heartbeat ────────>│  Every 30s: report progress + speed
  |<── continue: true/false ───────│
  |                                |
  |── POST /api/work/complete ────>│  Report chunk done
  |<── accepted: true ─────────────│
  |                                |
  |   [Loop: get next chunk]       |
```

### KeyHunt Scanning Engine

The worker runs [KeyHunt-Cuda](https://github.com/Soumya001/KeyHunt-Cuda) — a GPU-accelerated Bitcoin private key scanner. For each assigned range:

1. KeyHunt generates private keys sequentially in the range
2. Derives the corresponding Bitcoin addresses (RIPEMD160 of SHA256 of public key)
3. Compares each against the target puzzle address
4. If found, immediately reports the private key to the pool

Performance benchmarks:
| GPU | Speed | Time per Chunk |
|-----|-------|----------------|
| RTX 3060 Ti | ~1.1 GKey/s | ~17 min |
| RTX 4070 | ~2.0 GKey/s | ~9 min |
| RTX 4090 | ~4.0 GKey/s | ~5 min |
| CPU (8 threads) | ~10 MKey/s | ~30 hours |

### Heartbeats & Fault Tolerance

Every 30 seconds, the worker sends a heartbeat with progress and speed. If heartbeats stop for 90 seconds, the server considers the worker dead and reassigns the chunk. This ensures:
- No work is lost if a worker crashes
- Partial progress is tracked
- Stale assignments are automatically recycled

### Anti-Cheat

The pool uses consistency-based validation:
- Speed checks (flagging impossibly fast completions)
- Timing analysis (verifying work duration matches claimed progress)

### Worker State Machine

```
         ┌──────────┐
    ┌───>│   IDLE   │<─────────────────┐
    │    └────┬─────┘                  │
    │         │ Start                  │ Stop
    │    ┌────v─────┐         ┌────────┴──┐
    │    │ SCANNING │──Pause─>│  PAUSED   │
    │    └────┬─────┘         └────┬──────┘
    │         │                    │ Resume
    │         │                    v
    │    Stop │              ┌────────────┐
    └─────────┘              │  SCANNING  │
                             └────────────┘
```

- **IDLE** — connected to pool, waiting for user to press Start
- **SCANNING** — actively scanning a chunk with KeyHunt
- **PAUSED** — current chunk finishes, then waits for Resume
- **ECO COOLDOWN** — brief cooldown between chunks (Eco mode only)
- **WAITING** — no work available from pool, retrying
- **RECONNECTING** — lost connection to pool, retrying

## Configuration

All config is stored in `config.json` inside the install directory:

```json
{
  "worker_name": "worker-MyPC",
  "gpu_id": 0,
  "device": "gpu",
  "cpu_threads": 4,
  "mode": "normal",
  "eco_cooldown": 60,
  "api_key": "auto-generated-on-first-run"
}
```

You can edit this file directly or use the Settings dialog in the GUI.

## FAQ

**Is this safe?** Yes. The worker runs KeyHunt-Cuda (open source GPU scanner) and reports results to the pool. Nothing else. Full source code is in `puzzle_worker.py`.

**What GPU do I need?** Any NVIDIA GPU with CUDA. GTX 1060+ recommended. You can also run in CPU-only mode.

**Can I use CPU only?** Yes. Select "CPU" in the Device dropdown or Settings. Set the number of threads to match your CPU cores.

**Multiple GPUs?** Run one instance per GPU with different GPU IDs configured in Settings.

**What if the key is found?** The pool securely stores the key. Rewards distributed to contributors based on their work contribution.

**What is Eco mode?** It adds a cooldown between chunks to reduce GPU temperature and power consumption. Useful for mining 24/7 without overheating.

**Does it work on macOS?** Yes, starting with v4.2.0. Download the macOS binary from Releases. Note: GPU mode requires NVIDIA CUDA, which is not available on Apple Silicon — use CPU mode on Macs.

**No CMD window popup?** The worker uses `CREATE_NO_WINDOW` on Windows to suppress console windows from KeyHunt and nvidia-smi.

## Donate

If you'd like to support the project:

| Currency | Address |
|----------|---------|
| **BTC** | `1KkfiPzShVeCmGozLPw5bdU7hwB3JQ6ASZ` |
| **BCH** | `147jaDxi81TgWiQcPASdSQTMAs8pyNJUGc` |

## License

Open source. See `puzzle_worker.py` for the full worker source code.
