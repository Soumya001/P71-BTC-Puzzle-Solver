"""Pool statistics and registration endpoints."""

import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..config import config
from .. import database as db
from .work import get_worker

router = APIRouter(prefix="/api")

_server_start_time = time.time()


class RegisterRequest(BaseModel):
    name: str


@router.post("/register")
async def register_worker(body: RegisterRequest):
    """Register a new worker and receive an API key."""
    if not body.name or len(body.name) > 64:
        return {"status": "error", "detail": "Name must be 1-64 characters"}
    result = await db.register_worker(body.name)
    return {
        "status": "ok",
        "worker_id": result["id"],
        "api_key": result["api_key"],
    }


@router.post("/heartbeat")
async def heartbeat(request: Request, worker: dict = Depends(get_worker)):
    """Worker heartbeat to signal liveness."""
    await db.update_last_seen(worker["id"])
    return {"status": "ok"}


@router.get("/stats")
async def pool_stats(request: Request):
    """Public pool statistics."""
    tracker = request.app.state.tracker

    db_stats = await db.get_pool_stats()
    leaderboard = await db.get_worker_leaderboard(limit=20)

    total = config.puzzle.total_chunks
    completed = db_stats["total_chunks_completed"]
    progress_pct = (completed / total * 100) if total > 0 else 0

    total_keyspace = config.puzzle.range_end - config.puzzle.range_start + 1
    keys_scanned = db_stats["total_keys_scanned"]
    keys_remaining = total_keyspace - keys_scanned

    # Estimate speed from uptime
    uptime = time.time() - _server_start_time
    keys_per_sec = keys_scanned / uptime if uptime > 0 and keys_scanned > 0 else 0
    eta_seconds = keys_remaining / keys_per_sec if keys_per_sec > 0 else 0

    return {
        "puzzle": {
            "number": config.puzzle.puzzle_number,
            "target_address": config.puzzle.target_address,
            "total_chunks": total,
            "chunk_size_bits": config.puzzle.chunk_bits,
            "chunk_size_keys": config.puzzle.chunk_size,
            "range_start": hex(config.puzzle.range_start),
            "range_end": hex(config.puzzle.range_end),
            "total_keyspace": total_keyspace,
        },
        "progress": {
            "chunks_completed": completed,
            "chunks_remaining": total - completed,
            "total_chunks": total,
            "percentage": round(progress_pct, 8),
            "total_keys_scanned": keys_scanned,
            "keys_remaining": keys_remaining,
        },
        "pool": {
            "total_workers": db_stats["total_workers"],
            "active_workers": db_stats["active_workers"],
            "active_assignments": tracker.active_assignments,
            "retry_queue_size": tracker.retry_queue_size,
            "cursor": tracker.cursor,
            "cursor_reached_end": tracker.cursor_reached_end,
            "keys_found": db_stats["keys_found"],
            "uptime_seconds": round(uptime),
            "est_keys_per_sec": round(keys_per_sec),
            "est_eta_seconds": round(eta_seconds),
        },
        "leaderboard": leaderboard,
    }
