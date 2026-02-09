"""SQLite database for worker management and statistics."""

import secrets
import time

import aiosqlite

from .config import config

_db: aiosqlite.Connection | None = None


async def init_db():
    """Initialize database connection and create tables."""
    global _db
    _db = await aiosqlite.connect(config.server.db_path)
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA synchronous=NORMAL")

    await _db.executescript("""
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            api_key TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL,
            last_seen REAL NOT NULL,
            is_banned INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS worker_stats (
            worker_id INTEGER PRIMARY KEY,
            chunks_completed INTEGER NOT NULL DEFAULT 0,
            total_keys BIGINT NOT NULL DEFAULT 0,
            canary_fails INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (worker_id) REFERENCES workers(id)
        );

        CREATE TABLE IF NOT EXISTS found_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            puzzle_id INTEGER NOT NULL,
            private_key TEXT NOT NULL,
            address TEXT NOT NULL,
            found_by_worker INTEGER,
            found_at REAL NOT NULL,
            FOREIGN KEY (found_by_worker) REFERENCES workers(id)
        );

        CREATE INDEX IF NOT EXISTS idx_workers_api_key ON workers(api_key);
    """)
    await _db.commit()


async def close_db():
    """Close database connection."""
    global _db
    if _db:
        await _db.close()
        _db = None


def _get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialized")
    return _db


async def register_worker(name: str) -> dict:
    """Register a new worker. Returns {id, api_key}."""
    db = _get_db()
    api_key = secrets.token_hex(32)
    now = time.time()
    cursor = await db.execute(
        "INSERT INTO workers (name, api_key, created_at, last_seen) VALUES (?, ?, ?, ?)",
        (name, api_key, now, now),
    )
    worker_id = cursor.lastrowid
    await db.execute(
        "INSERT INTO worker_stats (worker_id) VALUES (?)",
        (worker_id,),
    )
    await db.commit()
    return {"id": worker_id, "api_key": api_key}


async def get_worker_by_api_key(api_key: str) -> dict | None:
    """Look up worker by API key."""
    db = _get_db()
    async with db.execute(
        "SELECT id, name, is_banned FROM workers WHERE api_key = ?",
        (api_key,),
    ) as cursor:
        row = await cursor.fetchone()
        if row:
            return {"id": row[0], "name": row[1], "is_banned": bool(row[2])}
    return None


async def update_last_seen(worker_id: int):
    """Update worker's last seen timestamp."""
    db = _get_db()
    await db.execute(
        "UPDATE workers SET last_seen = ? WHERE id = ?",
        (time.time(), worker_id),
    )
    await db.commit()


async def record_chunk_completion(worker_id: int, keys_scanned: int):
    """Record that a worker completed a chunk."""
    db = _get_db()
    await db.execute(
        """UPDATE worker_stats
           SET chunks_completed = chunks_completed + 1,
               total_keys = total_keys + ?
           WHERE worker_id = ?""",
        (keys_scanned, worker_id),
    )
    await db.commit()


async def record_canary_fail(worker_id: int) -> int:
    """Record a canary failure. Returns new total failures."""
    db = _get_db()
    await db.execute(
        "UPDATE worker_stats SET canary_fails = canary_fails + 1 WHERE worker_id = ?",
        (worker_id,),
    )
    await db.commit()
    async with db.execute(
        "SELECT canary_fails FROM worker_stats WHERE worker_id = ?",
        (worker_id,),
    ) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0


async def ban_worker(worker_id: int):
    """Ban a worker."""
    db = _get_db()
    await db.execute(
        "UPDATE workers SET is_banned = 1 WHERE id = ?",
        (worker_id,),
    )
    await db.commit()


async def record_found_key(puzzle_id: int, private_key: str, address: str, worker_id: int):
    """Record a found key."""
    db = _get_db()
    await db.execute(
        "INSERT INTO found_keys (puzzle_id, private_key, address, found_by_worker, found_at) VALUES (?, ?, ?, ?, ?)",
        (puzzle_id, private_key, address, worker_id, time.time()),
    )
    await db.commit()


async def get_pool_stats() -> dict:
    """Get aggregate pool statistics."""
    db = _get_db()

    async with db.execute("SELECT COUNT(*) FROM workers WHERE is_banned = 0") as c:
        total_workers = (await c.fetchone())[0]

    async with db.execute(
        "SELECT COUNT(*) FROM workers WHERE is_banned = 0 AND last_seen > ?",
        (time.time() - 300,),
    ) as c:
        active_workers = (await c.fetchone())[0]

    async with db.execute(
        "SELECT COALESCE(SUM(chunks_completed), 0), COALESCE(SUM(total_keys), 0) FROM worker_stats"
    ) as c:
        row = await c.fetchone()
        total_chunks_done = row[0]
        total_keys_scanned = row[1]

    async with db.execute("SELECT COUNT(*) FROM found_keys") as c:
        found_count = (await c.fetchone())[0]

    return {
        "total_workers": total_workers,
        "active_workers": active_workers,
        "total_chunks_completed": total_chunks_done,
        "total_keys_scanned": total_keys_scanned,
        "keys_found": found_count,
    }


async def get_worker_leaderboard(limit: int = 20) -> list[dict]:
    """Get top workers by chunks completed."""
    db = _get_db()
    rows = []
    async with db.execute(
        """SELECT w.name, ws.chunks_completed, ws.total_keys, ws.canary_fails
           FROM worker_stats ws
           JOIN workers w ON w.id = ws.worker_id
           WHERE w.is_banned = 0
           ORDER BY ws.chunks_completed DESC
           LIMIT ?""",
        (limit,),
    ) as cursor:
        async for row in cursor:
            rows.append({
                "name": row[0],
                "chunks_completed": row[1],
                "total_keys": row[2],
                "canary_fails": row[3],
            })
    return rows
