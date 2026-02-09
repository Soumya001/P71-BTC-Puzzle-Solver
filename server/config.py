"""Pool configuration and puzzle parameters."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


@dataclass
class PuzzleConfig:
    puzzle_number: int = 71
    # Keyspace: 2^70 to 2^71 - 1
    range_start: int = 2**70
    range_end: int = 2**71 - 1
    target_address: str = "1PWo3JeB9jrGwfHDNpdGK54CRas7fsVzXU"
    # Chunk size: 2^36 keys (~62s at 1.1 GKey/s)
    chunk_bits: int = 36
    chunk_size: int = 2**36  # 68,719,476,736 keys per chunk
    # Total chunks: 2^(70-36) = 2^34
    total_chunks: int = 2**34  # 17,179,869,184


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8420
    # Batch: number of chunks per work request
    batch_size: int = 4
    # Assignment deadline (seconds) - worker must report within this time
    assignment_timeout: int = 300  # 5 minutes
    # Reaper interval (seconds)
    reaper_interval: int = 60
    # Bitmap flush interval (seconds)
    bitmap_flush_interval: int = 30
    # State save interval (seconds)
    state_save_interval: int = 10
    # Canary keys per chunk
    canaries_per_chunk: int = 5
    # Max canary failures before ban
    max_canary_fails: int = 3
    # Database path
    db_path: str = str(DATA_DIR / "pool.db")
    # Bitmap path
    bitmap_path: str = str(DATA_DIR / "bitmap.bin")
    # State file
    state_path: str = str(DATA_DIR / "pool_state.json")


@dataclass
class Config:
    puzzle: PuzzleConfig = field(default_factory=PuzzleConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        config = cls()
        config_path = Path(path) if path else BASE_DIR / "config.json"
        if config_path.exists():
            with open(config_path) as f:
                data = json.load(f)
            if "puzzle" in data:
                p = data["puzzle"]
                if "puzzle_number" in p:
                    config.puzzle.puzzle_number = p["puzzle_number"]
                if "target_address" in p:
                    config.puzzle.target_address = p["target_address"]
                if "range_start" in p:
                    config.puzzle.range_start = int(p["range_start"], 16) if isinstance(p["range_start"], str) else p["range_start"]
                if "range_end" in p:
                    config.puzzle.range_end = int(p["range_end"], 16) if isinstance(p["range_end"], str) else p["range_end"]
                if "chunk_bits" in p:
                    config.puzzle.chunk_bits = p["chunk_bits"]
                    config.puzzle.chunk_size = 2 ** p["chunk_bits"]
                    total_keys = config.puzzle.range_end - config.puzzle.range_start + 1
                    config.puzzle.total_chunks = total_keys // config.puzzle.chunk_size
            if "server" in data:
                s = data["server"]
                for key in ("host", "port", "batch_size", "assignment_timeout",
                            "reaper_interval", "bitmap_flush_interval",
                            "state_save_interval", "canaries_per_chunk",
                            "max_canary_fails"):
                    if key in s:
                        setattr(config.server, key, s[key])
        return config


# Global config instance
config = Config.load()
