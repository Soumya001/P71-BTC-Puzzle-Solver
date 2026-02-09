"""Work assignment and completion endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..config import config
from .. import database as db

router = APIRouter(prefix="/api")


class WorkCompletionRequest(BaseModel):
    chunk_id: int
    canary_keys: dict[str, str]  # {address: privkey_hex}


class WorkCompletionBatchRequest(BaseModel):
    results: list[WorkCompletionRequest]


async def get_worker(request: Request) -> dict:
    """Dependency: extract and validate worker from API key."""
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    worker = await db.get_worker_by_api_key(api_key)
    if not worker:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if worker["is_banned"]:
        raise HTTPException(status_code=403, detail="Worker is banned")
    return worker


@router.get("/work")
async def get_work(request: Request, worker: dict = Depends(get_worker)):
    """Get a batch of chunks to scan."""
    tracker = request.app.state.tracker
    canary_gen = request.app.state.canary_gen

    await db.update_last_seen(worker["id"])

    assignments = await tracker.assign_batch(
        worker_id=worker["id"],
        batch_size=config.server.batch_size,
        canary_generator=canary_gen,
    )

    if not assignments:
        return {
            "status": "no_work",
            "message": "No chunks available. Pool may be fully scanned or all chunks assigned.",
        }

    return {
        "status": "ok",
        "target_address": config.puzzle.target_address,
        "chunks": assignments,
    }


@router.post("/work")
async def report_work(
    body: WorkCompletionBatchRequest,
    request: Request,
    worker: dict = Depends(get_worker),
):
    """Report completion of assigned chunks with canary proofs."""
    tracker = request.app.state.tracker
    canary_gen = request.app.state.canary_gen
    accepted = 0
    rejected = 0

    await db.update_last_seen(worker["id"])

    for result in body.results:
        assignment = tracker.get_assignment(result.chunk_id)
        if assignment is None:
            # Assignment may have expired and been reassigned - skip
            rejected += 1
            continue

        if assignment.worker_id != worker["id"]:
            rejected += 1
            continue

        # Verify canary keys
        if assignment.canary_keys:
            passed, failures = canary_gen.verify(
                assignment.canary_keys, result.canary_keys
            )
            if not passed:
                total_fails = await db.record_canary_fail(worker["id"])
                tracker.remove_assignment(result.chunk_id)
                if total_fails >= config.server.max_canary_fails:
                    await db.ban_worker(worker["id"])
                    raise HTTPException(
                        status_code=403,
                        detail=f"Banned: too many canary failures ({total_fails})",
                    )
                rejected += 1
                continue

        # Mark complete
        success = await tracker.complete_chunk(result.chunk_id, worker["id"])
        if success:
            await db.record_chunk_completion(worker["id"], config.puzzle.chunk_size)
            accepted += 1
        else:
            rejected += 1

    return {
        "status": "ok",
        "accepted": accepted,
        "rejected": rejected,
    }
