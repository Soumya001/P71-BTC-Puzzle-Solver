"""Gap scanner: Phase 2 bitmap sweep for missed chunks.

Activates when the cursor reaches the end of the keyspace.
Scans the bitmap for any unset bits (missed chunks) and queues them.
"""

import struct
from collections import deque

from .bitmap import BitmapManager
from .config import config


class GapScanner:
    def __init__(self, bitmap: BitmapManager):
        self._bitmap = bitmap
        self._total_chunks = config.puzzle.total_chunks
        self._size_bytes = (self._total_chunks + 7) // 8
        self._gap_queue: deque[int] = deque()
        self._last_scan_offset = 0
        self._scan_complete = False

    @property
    def has_gaps(self) -> bool:
        return len(self._gap_queue) > 0

    @property
    def gap_count(self) -> int:
        return len(self._gap_queue)

    def get_gaps(self, count: int) -> list[int]:
        """Get up to 'count' gap chunk IDs."""
        result = []
        for _ in range(min(count, len(self._gap_queue))):
            result.append(self._gap_queue.popleft())
        return result

    def scan(self, max_bytes: int = 0) -> list[int]:
        """Scan bitmap for unset bits. Returns list of gap chunk IDs found.

        Scans in 64-bit words for speed. If max_bytes is 0, scans entire bitmap.
        """
        mm = self._bitmap._mm
        if mm is None:
            return []

        gaps = []
        offset = self._last_scan_offset
        end = self._size_bytes if max_bytes == 0 else min(offset + max_bytes, self._size_bytes)

        # Align to 8-byte boundary
        while offset % 8 != 0 and offset < end:
            byte_val = mm[offset]
            if byte_val != 0xFF:
                # Check individual bits
                base_chunk = offset * 8
                for bit in range(8):
                    chunk_id = base_chunk + bit
                    if chunk_id < self._total_chunks and not (byte_val & (1 << bit)):
                        gaps.append(chunk_id)
                        self._gap_queue.append(chunk_id)
            offset += 1

        # Scan in 8-byte words
        view = memoryview(mm)
        while offset + 8 <= end:
            word = struct.unpack_from("<Q", view, offset)[0]
            if word != 0xFFFFFFFFFFFFFFFF:
                # At least one unset bit in this word
                base_chunk = offset * 8
                for bit in range(64):
                    chunk_id = base_chunk + bit
                    if chunk_id < self._total_chunks and not (word & (1 << bit)):
                        gaps.append(chunk_id)
                        self._gap_queue.append(chunk_id)
            offset += 8

        # Handle remaining bytes
        while offset < end:
            byte_val = mm[offset]
            if byte_val != 0xFF:
                base_chunk = offset * 8
                for bit in range(8):
                    chunk_id = base_chunk + bit
                    if chunk_id < self._total_chunks and not (byte_val & (1 << bit)):
                        gaps.append(chunk_id)
                        self._gap_queue.append(chunk_id)
            offset += 1

        self._last_scan_offset = offset
        if offset >= self._size_bytes:
            self._scan_complete = True
            self._last_scan_offset = 0  # Reset for next full scan

        return gaps
