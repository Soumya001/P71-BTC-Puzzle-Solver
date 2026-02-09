#!/usr/bin/env python3
"""Bitcoin Puzzle Pool Worker Client.

Connects to the pool server, receives work assignments, runs KeyHunt-Cuda,
and reports results back to the server.
"""

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path

import requests

from runner import KeyHuntRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent / "worker_config.json"


class PoolWorker:
    def __init__(self, pool_url: str, worker_name: str, keyhunt_path: str, gpu_id: int = 0):
        self._pool_url = pool_url.rstrip("/")
        self._worker_name = worker_name
        self._keyhunt_path = keyhunt_path
        self._gpu_id = gpu_id
        self._api_key: str | None = None
        self._runner = KeyHuntRunner(keyhunt_path, gpu_id)
        self._running = True
        self._session = requests.Session()
        self._session.timeout = 30

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        logger.info("Received signal %d, shutting down...", signum)
        self._running = False
        self._runner.kill()

    def _headers(self) -> dict:
        h = {}
        if self._api_key:
            h["X-API-Key"] = self._api_key
        return h

    def _load_config(self) -> bool:
        """Load saved API key from config file."""
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text())
            self._api_key = data.get("api_key")
            if self._api_key:
                logger.info("Loaded API key from config")
                return True
        return False

    def _save_config(self):
        """Save API key to config file."""
        CONFIG_FILE.write_text(json.dumps({
            "api_key": self._api_key,
            "worker_name": self._worker_name,
            "pool_url": self._pool_url,
        }, indent=2))

    def register(self):
        """Register with the pool server."""
        if self._load_config():
            return

        logger.info("Registering with pool as '%s'...", self._worker_name)
        resp = self._session.post(
            f"{self._pool_url}/api/register",
            json={"name": self._worker_name},
        )
        resp.raise_for_status()
        data = resp.json()
        if data["status"] != "ok":
            raise RuntimeError(f"Registration failed: {data}")

        self._api_key = data["api_key"]
        self._save_config()
        logger.info("Registered as worker #%d", data["worker_id"])

    def get_work(self) -> dict | None:
        """Request a batch of work from the pool."""
        try:
            resp = self._session.get(
                f"{self._pool_url}/api/work",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            if data["status"] == "no_work":
                logger.info("No work available: %s", data.get("message", ""))
                return None
            return data
        except requests.RequestException as e:
            logger.error("Failed to get work: %s", e)
            return None

    def report_work(self, results: list[dict]) -> dict | None:
        """Report completed work to the pool."""
        try:
            resp = self._session.post(
                f"{self._pool_url}/api/work",
                headers=self._headers(),
                json={"results": results},
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("Failed to report work: %s", e)
            return None

    def report_found(self, chunk_id: int, private_key: str) -> dict | None:
        """Report a found puzzle key."""
        try:
            resp = self._session.post(
                f"{self._pool_url}/api/found",
                headers=self._headers(),
                json={"chunk_id": chunk_id, "private_key": private_key},
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("Failed to report found key: %s", e)
            return None

    def heartbeat(self):
        """Send heartbeat to server."""
        try:
            self._session.post(
                f"{self._pool_url}/api/heartbeat",
                headers=self._headers(),
            )
        except requests.RequestException:
            pass

    def run(self):
        """Main worker loop."""
        self.register()
        logger.info("Worker started. Pool: %s", self._pool_url)

        consecutive_no_work = 0

        while self._running:
            # Get work
            work = self.get_work()
            if work is None:
                consecutive_no_work += 1
                wait_time = min(30 * consecutive_no_work, 300)
                logger.info("Waiting %ds before retry...", wait_time)
                time.sleep(wait_time)
                continue

            consecutive_no_work = 0
            target_address = work["target_address"]
            chunks = work["chunks"]
            logger.info("Received %d chunks to scan", len(chunks))

            completed_results = []

            for chunk in chunks:
                if not self._running:
                    break

                chunk_id = chunk["chunk_id"]
                range_start = chunk["range_start"]
                range_end = chunk["range_end"]
                canary_addresses = chunk["canary_addresses"]

                logger.info(
                    "Scanning chunk %d: %s to %s (%d canaries)",
                    chunk_id,
                    range_start,
                    range_end,
                    len(canary_addresses),
                )

                result = self._runner.run_chunk(
                    range_start=range_start,
                    range_end=range_end,
                    target_address=target_address,
                    canary_addresses=canary_addresses,
                )

                if result["status"] == "found":
                    # JACKPOT!
                    found = result["found_key"]
                    logger.critical(
                        "TARGET KEY FOUND! Address: %s, Key: %s",
                        found["address"],
                        found["privkey"],
                    )
                    self.report_found(chunk_id, found["privkey"])
                    # Still report the chunk completion
                    completed_results.append({
                        "chunk_id": chunk_id,
                        "canary_keys": result["canary_keys"],
                    })
                    break

                if result["status"] in ("complete", "timeout"):
                    completed_results.append({
                        "chunk_id": chunk_id,
                        "canary_keys": result["canary_keys"],
                    })
                    logger.info(
                        "Chunk %d done. Found %d/%d canaries.",
                        chunk_id,
                        len(result["canary_keys"]),
                        len(canary_addresses),
                    )
                elif result["status"] == "error":
                    logger.error("Chunk %d failed with error", chunk_id)

            # Report all completed chunks
            if completed_results:
                report = self.report_work(completed_results)
                if report:
                    logger.info(
                        "Reported %d chunks: %d accepted, %d rejected",
                        len(completed_results),
                        report.get("accepted", 0),
                        report.get("rejected", 0),
                    )

        logger.info("Worker stopped.")


def main():
    parser = argparse.ArgumentParser(description="Bitcoin Puzzle Pool Worker")
    parser.add_argument(
        "--pool-url",
        required=True,
        help="Pool server URL (e.g., http://1.2.3.4:8420)",
    )
    parser.add_argument(
        "--name",
        default="worker",
        help="Worker name for identification",
    )
    parser.add_argument(
        "--keyhunt-path",
        default="/usr/local/bin/KeyHunt",
        help="Path to KeyHunt-Cuda binary",
    )
    parser.add_argument(
        "--gpu-id",
        type=int,
        default=0,
        help="GPU device ID to use",
    )

    args = parser.parse_args()

    worker = PoolWorker(
        pool_url=args.pool_url,
        worker_name=args.name,
        keyhunt_path=args.keyhunt_path,
        gpu_id=args.gpu_id,
    )
    worker.run()


if __name__ == "__main__":
    main()
