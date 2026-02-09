# P71 BTC Puzzle Solver - Pool Edition

A distributed pool system for solving Bitcoin Puzzle #71. Workers worldwide connect to a central server and collectively scan the keyspace with **zero duplicate work**.

## Architecture

```
Workers (worldwide)                    Pool Server
+-----------------------+              +---------------------------+
| puzzle_worker.py      |  REST API    | FastAPI server            |
|   ├─ Modern GUI       | <---------> |   ├─ bitmap (2GB mmap)    |
|   ├─ Run KeyHunt-Cuda |              |   ├─ assignment tracker   |
|   ├─ Parse output     |              |   ├─ canary anti-cheat    |
|   └─ Report results   |              |   ├─ SQLite database      |
+-----------------------+              +---------------------------+
```

- **Bitmap tracking**: 2 GB memory-mapped file, 1 bit per chunk, O(1) lookups
- **Sequential cursor**: Monotonically increasing chunk assignment, zero overlaps
- **Canary verification**: 5 hidden keys per chunk to catch cheaters
- **Chunk size**: 2^36 keys per chunk (~62 sec at 1.1 GKey/s)

## Dashboard

Live stats at **[starnetlive.space](https://starnetlive.space)**

## Quick Start - Worker

### Option 1: Download Binary (Recommended)

Download from [Releases](https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases):

- **Windows**: `puzzle-worker.exe` — double-click to run
- **Linux**: `puzzle-worker-linux` — `chmod +x puzzle-worker-linux && ./puzzle-worker-linux`

A modern GUI setup window will guide you through configuration.

### Option 2: Run from Source

```bash
pip install customtkinter
python worker/puzzle_worker.py
```

### Option 3: One-liner (Linux)

```bash
curl -sL https://starnetlive.space/download/puzzle-worker.py | python3 - --no-gui
```

### Requirements

- **NVIDIA GPU** with CUDA drivers
- **[KeyHunt-Cuda](https://github.com/albertobsd/keyhunt)** binary built or downloaded

## Server Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m server.main
```

Server runs on port 8420 by default. Edit `config.json` for puzzle parameters.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/register` | POST | Register new worker |
| `/api/work` | GET | Get batch of 4 chunks |
| `/api/work` | POST | Report completed chunks |
| `/api/found` | POST | Report found key |
| `/api/stats` | GET | Pool statistics |
| `/api/heartbeat` | POST | Worker heartbeat |

## Project Structure

```
├── server/
│   ├── main.py           # FastAPI app with background tasks
│   ├── config.py          # Puzzle params, chunk size, timeouts
│   ├── bitmap.py          # 2GB mmap bitmap for chunk tracking
│   ├── assignments.py     # Cursor-based chunk assignment
│   ├── canary.py          # Anti-cheat canary key verification
│   ├── database.py        # SQLite (workers, stats, found keys)
│   ├── gap_scanner.py     # Scans for missed chunks
│   ├── static/index.html  # Dashboard frontend
│   └── routes/
│       ├── work.py        # Work assignment & reporting
│       ├── found.py       # Key found reporting
│       └── stats.py       # Pool statistics
├── worker/
│   ├── puzzle_worker.py   # Standalone worker with GUI (single file)
│   ├── worker.py          # Modular worker (uses runner.py)
│   ├── runner.py          # KeyHunt-Cuda subprocess manager
│   └── install.sh         # Setup script
├── config.json            # Puzzle configuration
└── requirements.txt       # Server dependencies
```

## Security

- Found keys are **only stored on the server** (database + encrypted file)
- No private keys are saved on worker machines
- No API endpoint exposes found keys publicly
- Workers are verified via canary keys to prevent cheating
