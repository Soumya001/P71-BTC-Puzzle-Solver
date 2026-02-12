<p align="center">
  <img src="assets/icons/icon.png" alt="BTC Puzzle Pool Logo" width="180"/>
</p>

<h1 align="center">Bitcoin Puzzle #71 — Pool Worker v4.2.0</h1>

<p align="center">
  <strong>Join the hunt for Bitcoin Puzzle #71. Download, run, mine.</strong>
</p>

<p align="center">
  <a href="https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases/latest"><img src="https://img.shields.io/github/v/release/Soumya001/P71-BTC-Puzzle-Solver?style=flat-square&color=f7931a" alt="Release"/></a>
  <a href="https://starnetlive.space"><img src="https://img.shields.io/badge/Dashboard-starnetlive.space-00e5ff?style=flat-square" alt="Dashboard"/></a>
  <a href="https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases"><img src="https://img.shields.io/github/downloads/Soumya001/P71-BTC-Puzzle-Solver/total?style=flat-square&color=00e676" alt="Downloads"/></a>
</p>

---

## What Is This?

The [Bitcoin Puzzle Transaction](https://privatekeys.pw/puzzles/bitcoin-puzzle-tx) locks BTC behind private keys in known address ranges. **Puzzle #71** has real BTC in a 2^70 keyspace. This project is a **distributed pool** — your machine scans a small chunk, and together we cover ground no single machine could.

## Download

[**Latest Release**](https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases/latest)

| Platform | File | Run |
|----------|------|-----|
| Windows | `puzzle-worker.exe` | Double-click |
| Linux | `puzzle-worker-linux` | `chmod +x && ./puzzle-worker-linux` |
| macOS | `puzzle-worker-macos` | `chmod +x && ./puzzle-worker-macos` |

---

## Installation Guide

### Windows

1. Download `puzzle-worker.exe` from [Releases](https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases/latest)
2. Double-click to run — Windows SmartScreen may warn you, click **More info > Run anyway**
3. The app creates `C:\PuzzlePool` with the scanning engine, config, and a desktop shortcut
4. Install [NVIDIA CUDA drivers](https://developer.nvidia.com/cuda-downloads) if using GPU mode
5. Press **Start** to begin

### Linux

```bash
# Download
wget https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases/latest/download/puzzle-worker-linux

# Make executable
chmod +x puzzle-worker-linux

# Run
./puzzle-worker-linux
```

The app creates `~/.puzzle-pool/` with the scanning engine, config, and a `.desktop` shortcut. Make sure you have NVIDIA drivers + CUDA toolkit installed for GPU mode:

```bash
# Ubuntu/Debian
sudo apt install nvidia-driver-550 nvidia-cuda-toolkit

# Fedora
sudo dnf install akmod-nvidia xorg-x11-drv-nvidia-cuda
```

### macOS

```bash
# Download
curl -LO https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases/latest/download/puzzle-worker-macos

# Make executable
chmod +x puzzle-worker-macos

# Run (macOS may block it — go to System Settings > Privacy & Security > Allow)
./puzzle-worker-macos
```

> **Note:** GPU mode requires NVIDIA CUDA which is not available on Mac. Use **CPU mode** on all Macs.

---

## Features

### v4.2.0
- Two-column UI with dark/light theme toggle
- Animated progress bars, ETA calculation
- Glass-like card design, bigger fonts
- macOS native build
- New puzzle-piece Bitcoin logo

### Controls & Modes
- **Start / Pause / Stop** — full scan control
- **Normal mode** — continuous scanning
- **Eco mode** — cooldown between chunks to reduce heat
- **GPU / CPU / CPU+GPU** device selection

### Settings (gear icon)
Worker name, GPU ID, CPU threads, device mode, scan mode, eco cooldown — all saved to `config.json`.

### Live Monitoring
Speed, progress, ETA, GPU temp/power/VRAM, CPU/RAM, heartbeat status, pool-wide stats, system tray background mining.

---

## How It Works

### The Puzzle

Puzzle #71 keyspace: **2^70 keys** (~1.18 sextillion). The pool splits it into **2^30 chunks** of **2^40 keys** each. At 1 GKey/s, one chunk takes ~18 min. The full space would take one GPU 37,000+ years — distributed across hundreds of workers, it becomes feasible.

### Architecture

```
                   +---------------------------------------------+
                   |                 Pool Server                 |
                   |              starnetlive.space              |
                   |                                             |
                   |  +--------+ +--------+ +-------+ +-------+  |
                   |  | Bitmap | | SQLite | | Stats | |  Gap  |  |
                   |  | 128 MB | |   DB   | | Engine| |Scanner|  |
                   |  +--------+ +--------+ +-------+ +-------+  |
                   |                                             |
                   |  API: /register /work /heartbeat /complete  |
                   +---------------------+-----------------------+
                                         |
                      +------------------+------------------+
                      |                  |                  |
                 +----+----+       +----+----+       +----+----+
                 | Worker1 |       | Worker2 |       | WorkerN |
                 | RTX3060 |       | RTX4090 |       |   CPU   |
                 | 1 GK/s  |       | 4 GK/s  |       | 10MK/s  |
                 +---------+       +---------+       +---------+
```

### Protocol

```
Worker                             Pool Server
  |-- GET  /api/register --------->|  get API key
  |-- GET  /api/work ------------->|  get chunk assignment
  |   [scan with KeyHunt]          |
  |-- POST /api/heartbeat -------->|  every 30s: progress + speed
  |-- POST /api/work/complete ---->|  report done
  |   [loop]                       |
```

### Scanning Engine

[KeyHunt-Cuda](https://github.com/Soumya001/KeyHunt-Cuda) — generates keys, derives addresses, compares against the target.

| GPU | Speed | Chunk Time |
|-----|-------|------------|
| RTX 3060 Ti | ~1.1 GKey/s | ~17 min |
| RTX 4070 | ~2.0 GKey/s | ~9 min |
| RTX 4090 | ~4.0 GKey/s | ~5 min |
| CPU (8 threads) | ~10 MKey/s | ~30 hrs |

### Fault Tolerance

Heartbeats every 30s. If missed for 90s, the chunk is reassigned. No work is ever lost.

### Worker State Machine

```
              +----------+
         +--->|   IDLE   |<-----------------+
         |    +----+-----+                  |
         |         | Start                  | Stop
         |    +----v-----+        +--------+--+
         |    | SCANNING +--Pause>|  PAUSED   |
         |    +----+-----+        +----+------+
         |         |                   | Resume
         |    Stop |                   v
         |         |             +----------+
         +---------+             | SCANNING |
                                 +----------+
```

**IDLE** — waiting for Start | **SCANNING** — running KeyHunt | **PAUSED** — waiting for Resume
**ECO COOLDOWN** — between chunks | **WAITING** — no work available | **RECONNECTING** — lost connection

### Configuration

All config stored in `config.json` inside the install directory:

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

Edit directly or use the Settings dialog (gear icon).

---

## FAQ

**Is this safe?** Yes. Open source — see `puzzle_worker.py`.

**What GPU?** Any NVIDIA with CUDA. GTX 1060+ recommended. CPU-only mode also available.

**Multiple GPUs?** Run one instance per GPU with different GPU IDs in Settings.

**Key found?** Pool stores it securely. Rewards distributed to contributors.

**Eco mode?** Cooldown between chunks to reduce heat. Good for 24/7 operation.

**macOS?** CPU mode only (no NVIDIA CUDA on Mac).

---

## Donate

Support the project:

| | Address |
|---|---------|
| **BTC** | `1KkfiPzShVeCmGozLPw5bdU7hwB3JQ6ASZ` |
| **BCH** | `147jaDxi81TgWiQcPASdSQTMAs8pyNJUGc` |

---

## License

Open source. Full source: [`puzzle_worker.py`](puzzle_worker.py)
