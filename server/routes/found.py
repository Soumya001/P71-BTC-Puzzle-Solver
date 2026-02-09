"""Found key reporting endpoint."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..canary import privkey_to_address
from ..config import config
from .. import database as db
from .work import get_worker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class FoundKeyRequest(BaseModel):
    chunk_id: int
    private_key: str  # hex string


@router.post("/found")
async def report_found_key(
    body: FoundKeyRequest,
    request: Request,
    worker: dict = Depends(get_worker),
):
    """Report a found puzzle key. This is the big moment."""
    # Verify the key produces the target address
    try:
        privkey_int = int(body.private_key, 16)
        computed_address = privkey_to_address(privkey_int)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid private key format")

    if computed_address != config.puzzle.target_address:
        logger.warning(
            "Worker %d reported false key: %s -> %s (expected %s)",
            worker["id"],
            body.private_key,
            computed_address,
            config.puzzle.target_address,
        )
        return {"status": "rejected", "detail": "Key does not match target address"}

    # FOUND IT!
    logger.critical(
        "KEY FOUND by worker %d (%s)! Private key: %s",
        worker["id"],
        worker["name"],
        body.private_key,
    )

    await db.record_found_key(
        puzzle_id=config.puzzle.puzzle_number,
        private_key=body.private_key,
        address=computed_address,
        worker_id=worker["id"],
    )

    # Write key to a prominent file
    found_path = config.server.state_path.replace("pool_state.json", "FOUND_KEY.txt")
    with open(found_path, "w") as f:
        f.write(f"PUZZLE #{config.puzzle.puzzle_number} SOLVED!\n")
        f.write(f"Private Key: {body.private_key}\n")
        f.write(f"Address: {computed_address}\n")
        f.write(f"Found by worker: {worker['id']} ({worker['name']})\n")

    return {
        "status": "found",
        "message": "Congratulations! Key verified and recorded.",
    }
