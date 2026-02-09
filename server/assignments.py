"""Assignment tracking: cursor-based sequential chunk assignment with retry queue."""

import asyncio
import time
from collections import deque
from dataclasses import dataclass

from .bitmap import BitmapManager
from .config import config


@dataclass
class Assignment:
    chunk_id: int
    worker_id: int
    assigned_at: float
    deadline: float
    canary_keys: list[dict] | None = None  # [{privkey_hex, address}, ...]


class AssignmentTracker:
    def __init__(self, bitmap: BitmapManager):
        self._bitmap = bitmap
        self._cursor: int = 0
        self._assignments: dict[int, Assignment] = {}  # chunk_id -> Assignment
        self._retry_queue: deque[int] = deque()
        self._lock = asyncio.Lock()
        self._timeout = config.server.assignment_timeout
        self._total_chunks = config.puzzle.total_chunks
        self._cursor_reached_end = False

    def restore_cursor(self, cursor: int):
        """Restore cursor from persisted state."""
        self._cursor = cursor

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def active_assignments(self) -> int:
        return len(self._assignments)

    @property
    def retry_queue_size(self) -> int:
        return len(self._retry_queue)

    @property
    def cursor_reached_end(self) -> bool:
        return self._cursor_reached_end

    async def assign_batch(self, worker_id: int, batch_size: int,
                           canary_generator=None) -> list[dict]:
        """Assign a batch of chunks to a worker.

        Returns list of {chunk_id, range_start, range_end, canary_addresses}.
        """
        async with self._lock:
            assignments = []
            now = time.time()
            deadline = now + self._timeout

            for _ in range(batch_size):
                chunk_id = self._next_chunk_id()
                if chunk_id is None:
                    break

                # Compute key range for this chunk
                range_start = config.puzzle.range_start + (chunk_id * config.puzzle.chunk_size)
                range_end = range_start + config.puzzle.chunk_size - 1

                # Generate canary keys if generator provided
                canary_data = None
                canary_addresses = []
                if canary_generator:
                    canary_data = canary_generator.generate(range_start, range_end)
                    canary_addresses = [c["address"] for c in canary_data]

                assignment = Assignment(
                    chunk_id=chunk_id,
                    worker_id=worker_id,
                    assigned_at=now,
                    deadline=deadline,
                    canary_keys=canary_data,
                )
                self._assignments[chunk_id] = assignment

                assignments.append({
                    "chunk_id": chunk_id,
                    "range_start": hex(range_start),
                    "range_end": hex(range_end),
                    "canary_addresses": canary_addresses,
                })

            return assignments

    def _next_chunk_id(self) -> int | None:
        """Get next chunk to assign: retry queue first, then cursor."""
        # Check retry queue first
        while self._retry_queue:
            chunk_id = self._retry_queue.popleft()
            # Skip if already completed or currently assigned
            if not self._bitmap.is_complete(chunk_id) and chunk_id not in self._assignments:
                return chunk_id

        # Advance cursor, skipping completed chunks
        while self._cursor < self._total_chunks:
            chunk_id = self._cursor
            self._cursor += 1
            if not self._bitmap.is_complete(chunk_id) and chunk_id not in self._assignments:
                return chunk_id

        self._cursor_reached_end = True
        return None

    async def complete_chunk(self, chunk_id: int, worker_id: int) -> bool:
        """Mark a chunk as completed. Returns True if assignment was valid."""
        async with self._lock:
            assignment = self._assignments.pop(chunk_id, None)
            if assignment is None:
                # Could be a late completion after timeout - still accept it
                pass
            elif assignment.worker_id != worker_id:
                # Wrong worker reporting - put back and reject
                self._assignments[chunk_id] = assignment
                return False

        await self._bitmap.mark_complete(chunk_id)
        return True

    def get_assignment(self, chunk_id: int) -> Assignment | None:
        """Get assignment details for canary verification."""
        return self._assignments.get(chunk_id)

    def remove_assignment(self, chunk_id: int):
        """Remove assignment without marking complete (e.g., failed canary)."""
        self._assignments.pop(chunk_id, None)

    async def reap_expired(self) -> int:
        """Move expired assignments to retry queue. Returns count of reaped."""
        now = time.time()
        expired = []
        async with self._lock:
            for chunk_id, assignment in list(self._assignments.items()):
                if now > assignment.deadline:
                    expired.append(chunk_id)

            for chunk_id in expired:
                del self._assignments[chunk_id]
                if not self._bitmap.is_complete(chunk_id):
                    self._retry_queue.append(chunk_id)

        return len(expired)

    def recover_cursor(self):
        """On restart, find first unset bit to set cursor if state is lost."""
        first_unset = self._bitmap.find_first_unset(0)
        if first_unset is not None:
            self._cursor = first_unset
        else:
            self._cursor = self._total_chunks
            self._cursor_reached_end = True
