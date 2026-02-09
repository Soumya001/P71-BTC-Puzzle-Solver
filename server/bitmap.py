"""Memory-mapped bitmap for tracking chunk completion.

Each bit represents one chunk (2^36 keys). Total bitmap size for puzzle #71:
2^34 bits = 2 GB. Uses mmap with MAP_SHARED for crash safety.
"""

import asyncio
import json
import mmap
import os
import struct
import time
from pathlib import Path

from .config import config


class BitmapManager:
    def __init__(self):
        self._bitmap_path = config.server.bitmap_path
        self._state_path = config.server.state_path
        self._total_chunks = config.puzzle.total_chunks
        # Bitmap size in bytes: ceil(total_chunks / 8)
        self._size_bytes = (self._total_chunks + 7) // 8
        self._fd: int | None = None
        self._mm: mmap.mmap | None = None
        self._lock = asyncio.Lock()

    async def open(self):
        """Open or create the bitmap file and mmap it."""
        path = Path(self._bitmap_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        created = not path.exists() or path.stat().st_size == 0
        self._fd = os.open(str(path), os.O_RDWR | os.O_CREAT)

        if created or os.fstat(self._fd).st_size < self._size_bytes:
            # Extend file to required size
            os.ftruncate(self._fd, self._size_bytes)

        self._mm = mmap.mmap(self._fd, self._size_bytes, access=mmap.ACCESS_WRITE)

    def close(self):
        """Close the mmap and file descriptor."""
        if self._mm is not None:
            self._mm.flush()
            self._mm.close()
            self._mm = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def is_complete(self, chunk_id: int) -> bool:
        """Check if a chunk is marked complete. Lock-free read."""
        byte_idx = chunk_id >> 3
        bit_idx = chunk_id & 7
        return bool(self._mm[byte_idx] & (1 << bit_idx))

    async def mark_complete(self, chunk_id: int):
        """Mark a chunk as complete with async lock for read-modify-write."""
        byte_idx = chunk_id >> 3
        bit_idx = chunk_id & 7
        async with self._lock:
            self._mm[byte_idx] = self._mm[byte_idx] | (1 << bit_idx)

    async def mark_complete_batch(self, chunk_ids: list[int]):
        """Mark multiple chunks as complete."""
        async with self._lock:
            for chunk_id in chunk_ids:
                byte_idx = chunk_id >> 3
                bit_idx = chunk_id & 7
                self._mm[byte_idx] = self._mm[byte_idx] | (1 << bit_idx)

    async def flush(self):
        """Flush mmap to disk."""
        if self._mm is not None:
            await asyncio.to_thread(self._mm.flush)

    def count_completed(self) -> int:
        """Count total completed chunks using popcount."""
        count = 0
        # Read in 8-byte (64-bit) words for speed
        view = memoryview(self._mm)
        offset = 0
        while offset + 8 <= self._size_bytes:
            word = struct.unpack_from("<Q", view, offset)[0]
            count += bin(word).count("1")
            offset += 8
        # Handle remaining bytes
        for i in range(offset, self._size_bytes):
            count += bin(self._mm[i]).count("1")
        return count

    def find_first_unset(self, start: int = 0) -> int | None:
        """Find the first unset bit starting from 'start'. Returns chunk_id or None."""
        chunk_id = start
        while chunk_id < self._total_chunks:
            byte_idx = chunk_id >> 3
            bit_idx = chunk_id & 7

            # Fast skip: if entire byte is 0xFF, skip 8 bits
            if bit_idx == 0 and byte_idx < self._size_bytes and self._mm[byte_idx] == 0xFF:
                chunk_id += 8
                continue

            # Check individual bit
            if not (self._mm[byte_idx] & (1 << bit_idx)):
                return chunk_id
            chunk_id += 1

        return None

    def save_state(self, cursor: int):
        """Persist cursor position to state file."""
        state = {
            "cursor": cursor,
            "timestamp": time.time(),
            "completed_chunks": None,  # Computed on demand, not every save
        }
        tmp_path = self._state_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f)
        os.replace(tmp_path, self._state_path)

    def load_state(self) -> dict:
        """Load persisted state."""
        path = Path(self._state_path)
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {"cursor": 0}
