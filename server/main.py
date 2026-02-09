"""FastAPI application with lifespan events and background tasks."""

import asyncio
import logging
from contextlib import asynccontextmanager

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .bitmap import BitmapManager
from .assignments import AssignmentTracker
from .canary import CanaryGenerator
from .config import config
from . import database as db
from .gap_scanner import GapScanner
from .routes import work, found, stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _reaper_loop(tracker: AssignmentTracker):
    """Periodically reap expired assignments."""
    while True:
        await asyncio.sleep(config.server.reaper_interval)
        try:
            count = await tracker.reap_expired()
            if count > 0:
                logger.info("Reaped %d expired assignments", count)
        except Exception:
            logger.exception("Reaper error")


async def _bitmap_flush_loop(bitmap: BitmapManager):
    """Periodically flush bitmap to disk."""
    while True:
        await asyncio.sleep(config.server.bitmap_flush_interval)
        try:
            await bitmap.flush()
        except Exception:
            logger.exception("Bitmap flush error")


async def _state_save_loop(bitmap: BitmapManager, tracker: AssignmentTracker):
    """Periodically save cursor position."""
    while True:
        await asyncio.sleep(config.server.state_save_interval)
        try:
            bitmap.save_state(tracker.cursor)
        except Exception:
            logger.exception("State save error")


async def _gap_scanner_loop(gap_scanner: GapScanner, tracker: AssignmentTracker):
    """Run gap scanner when cursor reaches end of keyspace."""
    while True:
        await asyncio.sleep(60)
        if tracker.cursor_reached_end:
            try:
                gaps = gap_scanner.scan()
                if gaps:
                    logger.info("Gap scanner found %d missed chunks", len(gaps))
            except Exception:
                logger.exception("Gap scanner error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("Starting Bitcoin Puzzle Pool Server")
    logger.info(
        "Puzzle #%d | Target: %s | Chunks: %s | Chunk size: 2^%d",
        config.puzzle.puzzle_number,
        config.puzzle.target_address,
        f"{config.puzzle.total_chunks:,}",
        config.puzzle.chunk_bits,
    )

    # Initialize components
    await db.init_db()

    bitmap = BitmapManager()
    await bitmap.open()

    tracker = AssignmentTracker(bitmap)

    # Restore cursor from state
    state = bitmap.load_state()
    saved_cursor = state.get("cursor", 0)
    if saved_cursor > 0:
        tracker.restore_cursor(saved_cursor)
        logger.info("Restored cursor to %d from state file", saved_cursor)
    else:
        tracker.recover_cursor()
        logger.info("Recovered cursor to %d from bitmap scan", tracker.cursor)

    canary_gen = CanaryGenerator()
    gap_scanner = GapScanner(bitmap)

    # Attach to app state for route access
    app.state.bitmap = bitmap
    app.state.tracker = tracker
    app.state.canary_gen = canary_gen
    app.state.gap_scanner = gap_scanner

    # Start background tasks
    bg_tasks = [
        asyncio.create_task(_reaper_loop(tracker)),
        asyncio.create_task(_bitmap_flush_loop(bitmap)),
        asyncio.create_task(_state_save_loop(bitmap, tracker)),
        asyncio.create_task(_gap_scanner_loop(gap_scanner, tracker)),
    ]

    logger.info("Server ready on %s:%d", config.server.host, config.server.port)

    yield

    # Shutdown
    logger.info("Shutting down...")
    for task in bg_tasks:
        task.cancel()
    await asyncio.gather(*bg_tasks, return_exceptions=True)

    bitmap.save_state(tracker.cursor)
    await bitmap.flush()
    bitmap.close()
    await db.close_db()
    logger.info("Shutdown complete")


app = FastAPI(title="Bitcoin Puzzle Pool", lifespan=lifespan)
app.include_router(work.router)
app.include_router(found.router)
app.include_router(stats.router)


STATIC_DIR = Path(__file__).parent / "static"
WORKER_DIR = Path(__file__).parent.parent / "worker"


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/download/worker.py")
async def download_worker():
    return FileResponse(WORKER_DIR / "worker.py", filename="worker.py")


@app.get("/download/runner.py")
async def download_runner():
    return FileResponse(WORKER_DIR / "runner.py", filename="runner.py")


@app.get("/download/install.sh")
async def download_install():
    return FileResponse(WORKER_DIR / "install.sh", filename="install.sh")


@app.get("/download/puzzle-worker-linux")
async def download_linux_binary():
    path = WORKER_DIR / "dist" / "puzzle-worker-linux"
    if path.exists():
        return FileResponse(path, filename="puzzle-worker-linux", media_type="application/octet-stream")
    return {"error": "Linux binary not available yet"}


@app.get("/download/puzzle-worker.py")
async def download_standalone_py():
    return FileResponse(WORKER_DIR / "puzzle_worker.py", filename="puzzle_worker.py")


def main():
    uvicorn.run(
        "server.main:app",
        host=config.server.host,
        port=config.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
