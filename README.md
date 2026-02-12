# Bitcoin Puzzle #71 — Pool Worker v4.1

Join the hunt for Bitcoin Puzzle #71. Download, run, mine. That's it.

**Dashboard:** [starnetlive.space](https://starnetlive.space)

## Download

Get the latest from [**Releases**](https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases):

| Platform | File | Run |
|----------|------|-----|
| Windows  | `puzzle-worker.exe` | Double-click |
| Linux    | `puzzle-worker-linux` | `chmod +x puzzle-worker-linux && ./puzzle-worker-linux` |

## Quick Start

1. Run the EXE
2. It auto-creates `C:\PuzzlePool` folder (Windows) or `~/.puzzle-pool` (Linux)
3. Downloads the scanning engine automatically (first run only)
4. Creates a desktop shortcut with icon
5. Connects to the pool and registers your worker
6. Press **Start** to begin scanning
7. Close the window — it keeps running in the system tray

**No setup. No configuration. No terminal commands.**

## Requirements

- **NVIDIA GPU** with CUDA drivers installed (for GPU mode)
- Internet connection (must stay connected to the pool)
- CPU-only mode available if you don't have an NVIDIA GPU

## Features

### Controls
- **Start / Pause / Stop** — full control over scanning
  - **Start** connects to the pool and begins scanning chunks
  - **Pause** finishes the current chunk, then waits until you resume
  - **Stop** immediately halts scanning and returns to idle
- Controls are in the toolbar, always accessible

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

Settings are saved to `config.json` and persist across restarts. Mode and eco changes apply immediately; device and thread changes apply on the next chunk.

### GUI
- Modern dark-themed interface with live stats
- System tray — mining continues in background when you close the window
- Real-time display: speed, GPU temp/power, heartbeat status, pool progress
- Log console showing all activity
- Auto-reconnect on connection loss
- Desktop shortcut with puzzle-piece Bitcoin icon

## How It Works

### Architecture

The system has two parts:

1. **Pool Server** ([starnetlive.space](https://starnetlive.space)) — coordinates work across all workers
2. **This Worker** — runs on your machine, scans key ranges assigned by the pool

### The Puzzle

Bitcoin Puzzle #71 has a known address with funds locked behind a private key somewhere in a 2^70 keyspace. The pool splits this keyspace into 2^30 chunks (each chunk = 2^40 keys). Workers scan chunks in parallel.

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

### KeyHunt Scanning

The worker runs [KeyHunt-Cuda](https://github.com/Soumya001/KeyHunt-Cuda) — a GPU-accelerated Bitcoin private key scanner. For each assigned range:

1. KeyHunt generates private keys in the range
2. Derives the corresponding Bitcoin addresses
3. Compares each against the target address
4. If found, reports the private key to the pool

Depending on your device setting, KeyHunt uses:
- **GPU mode:** `-m address -g --gpui <id> --range S:E TARGET`
- **CPU mode:** `-m address -t <threads> --range S:E TARGET`
- **CPU+GPU:** `-m address -g --gpui <id> -t <threads> --range S:E TARGET`

### Heartbeats

Every 30 seconds during scanning, the worker sends a heartbeat to the pool with:
- Current progress percentage
- Scanning speed (keys/sec)
- How far into the range it has scanned

If 3 heartbeats are missed (90s timeout), the server marks the worker as dead and reassigns the chunk. This ensures no work is lost if a worker crashes — partial progress is preserved.

### Anti-Cheat

The pool uses consistency-based validation:
- Speed checks (flagging impossibly fast completions)
- Timing analysis (verifying work duration matches claimed progress)

### State Machine

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

**Is this safe?** Yes. The worker runs KeyHunt-Cuda (open source GPU scanner) and reports results to the pool. Nothing else.

**What GPU do I need?** Any NVIDIA GPU with CUDA. GTX 1060+ recommended. You can also run in CPU-only mode.

**Can I use CPU only?** Yes. Select "CPU" in the Device dropdown or Settings. Set the number of threads to match your CPU cores.

**Multiple GPUs?** Run one instance per GPU with different GPU IDs configured in Settings.

**What if the key is found?** The pool securely stores the key. Rewards distributed to contributors.

**What is Eco mode?** It adds a cooldown between chunks to reduce GPU temperature and power consumption. Useful for mining 24/7 without overheating.

**Can I see the source code?** Yes — `puzzle_worker.py` in this repo is the full source.

**No CMD window popup?** v4.1 uses `CREATE_NO_WINDOW` on Windows to suppress console windows from KeyHunt and nvidia-smi.

## Scanning Engine

The GPU scanning engine is [KeyHunt-Cuda](https://github.com/Soumya001/KeyHunt-Cuda) — our fork with build fixes for modern GCC/CUDA toolchains, tested on RTX 3060 Ti (~1.1 GKey/s). The worker auto-downloads the correct binary for your platform on first run.
