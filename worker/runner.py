"""KeyHunt-Cuda subprocess manager.

Launches KeyHunt-Cuda for each chunk, parses output for found keys,
progress updates, and completion signals.
"""

import logging
import os
import re
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Patterns for parsing KeyHunt-Cuda output
FOUND_PATTERN = re.compile(r"PubAddress:\s*(\S+)")
PRIVKEY_PATTERN = re.compile(r"Priv\s*\(HEX\):\s*([0-9a-fA-F]+)")
PROGRESS_PATTERN = re.compile(r"\[.*?(\d+\.?\d*)%\]")
BYE_PATTERN = re.compile(r"BYE")


class KeyHuntRunner:
    def __init__(self, keyhunt_path: str, gpu_id: int = 0):
        self._keyhunt_path = keyhunt_path
        self._gpu_id = gpu_id
        self._process: subprocess.Popen | None = None

    def run_chunk(
        self,
        range_start: str,
        range_end: str,
        target_address: str,
        canary_addresses: list[str],
        timeout: int = 600,
    ) -> dict:
        """Run KeyHunt-Cuda on a chunk range.

        Args:
            range_start: Hex string (e.g., "0x400000000000000000")
            range_end: Hex string
            target_address: The puzzle target Bitcoin address
            canary_addresses: List of canary Bitcoin addresses to find
            timeout: Max seconds before killing process

        Returns:
            {
                "status": "complete" | "found" | "error" | "timeout",
                "found_key": {"address": str, "privkey": str} | None,
                "canary_keys": {address: privkey_hex, ...},
                "progress": float,
            }
        """
        # All addresses to search for: target + canaries
        all_addresses = [target_address] + canary_addresses

        # Write addresses to temp file
        addr_file = Path(f"/tmp/puzzle_addrs_{os.getpid()}.txt")
        addr_file.write_text("\n".join(all_addresses) + "\n")

        # Clean hex strings (remove 0x prefix)
        start_clean = range_start.lstrip("0x") if range_start.startswith("0x") else range_start
        end_clean = range_end.lstrip("0x") if range_end.startswith("0x") else range_end

        cmd = [
            self._keyhunt_path,
            "-m", "address",
            "-f", str(addr_file),
            "-r", f"{start_clean}:{end_clean}",
            "-t", "0",  # 0 = use GPU
            "-b", "0",  # auto blocks
            "-g", str(self._gpu_id),
            "-q",  # quiet mode (less output clutter)
        ]

        logger.info("Running: %s", " ".join(cmd))
        result = {
            "status": "complete",
            "found_key": None,
            "canary_keys": {},
            "progress": 0.0,
        }

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            start_time = time.time()
            current_address = None

            for line in self._process.stdout:
                line = line.strip()
                if not line:
                    continue

                # Check for found address
                addr_match = FOUND_PATTERN.search(line)
                if addr_match:
                    current_address = addr_match.group(1)

                # Check for private key (follows address line)
                key_match = PRIVKEY_PATTERN.search(line)
                if key_match and current_address:
                    privkey_hex = key_match.group(1)

                    if current_address == target_address:
                        # PUZZLE KEY FOUND!
                        result["found_key"] = {
                            "address": current_address,
                            "privkey": privkey_hex,
                        }
                        result["status"] = "found"
                        logger.critical("TARGET KEY FOUND: %s", privkey_hex)
                        self.kill()
                        break
                    elif current_address in canary_addresses:
                        result["canary_keys"][current_address] = "0x" + privkey_hex
                        logger.debug("Canary found: %s", current_address)

                    current_address = None

                # Check for progress
                prog_match = PROGRESS_PATTERN.search(line)
                if prog_match:
                    result["progress"] = float(prog_match.group(1))

                # Check for completion
                if BYE_PATTERN.search(line):
                    result["status"] = "complete"
                    result["progress"] = 100.0

                # Timeout check
                if time.time() - start_time > timeout:
                    logger.warning("Chunk timed out after %ds", timeout)
                    result["status"] = "timeout"
                    self.kill()
                    break

            # Wait for process to finish
            if self._process.poll() is None:
                self._process.wait(timeout=10)

            returncode = self._process.returncode
            if returncode and returncode != 0 and result["status"] == "complete":
                logger.warning("KeyHunt exited with code %d", returncode)
                result["status"] = "error"

        except Exception as e:
            logger.exception("Runner error: %s", e)
            result["status"] = "error"
            self.kill()
        finally:
            self._process = None
            # Cleanup temp file
            try:
                addr_file.unlink(missing_ok=True)
            except Exception:
                pass

        return result

    def kill(self):
        """Kill the running KeyHunt process."""
        if self._process and self._process.poll() is None:
            try:
                self._process.kill()
                self._process.wait(timeout=5)
            except Exception:
                pass
