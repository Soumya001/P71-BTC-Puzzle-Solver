# Bitcoin Puzzle #71 — Pool Worker

Join the hunt for Bitcoin Puzzle #71. Download, run, mine. That's it.

**Dashboard:** [starnetlive.space](https://starnetlive.space)

## Download

Get the latest from [**Releases**](https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases):

| Platform | File | Run |
|----------|------|-----|
| Windows  | `puzzle-worker.exe` | Double-click |
| Linux    | `puzzle-worker-linux` | `chmod +x puzzle-worker-linux && ./puzzle-worker-linux` |

## What Happens

1. Run the EXE
2. It auto-creates `C:\PuzzlePool` folder (Windows) or `~/.puzzle-pool` (Linux)
3. Downloads the scanning engine automatically (first run only)
4. Creates a desktop shortcut with icon
5. Connects to the pool and starts scanning
6. Close the window — it keeps mining in the system tray

**No setup. No configuration. No terminal commands.**

## Requirements

- **NVIDIA GPU** with CUDA drivers installed
- Internet connection (must stay connected to the pool)

## Features

- Modern dark-themed GUI with live stats
- System tray — mining continues in background when you close the window
- Auto-reconnect on connection loss
- Shows your speed, GPU temp, chunks completed, pool progress
- Desktop shortcut with icon created automatically

## How It Works

The pool server splits Puzzle #71's keyspace (2^70 keys) into chunks. Your GPU scans chunks assigned by the pool. Results are verified via canary keys (anti-cheat). Progress is tracked on the [dashboard](https://starnetlive.space).

No private keys are ever stored on your machine.

## FAQ

**Is this safe?** Yes. The worker runs KeyHunt-Cuda (open source GPU scanner) and reports results to the pool. Nothing else.

**What GPU do I need?** Any NVIDIA GPU with CUDA. GTX 1060+ recommended.

**Multiple GPUs?** Run one instance per GPU — they auto-register as separate workers.

**What if the key is found?** The pool securely stores the key. Rewards distributed to contributors.

**Can I see the source code?** Yes — `puzzle_worker.py` in this repo is the full source.
