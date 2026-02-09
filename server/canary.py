"""Canary key generation and verification for anti-cheat.

Generates random private keys within a chunk's range, computes their
Bitcoin addresses, and verifies workers return the correct private keys.
"""

import hashlib
import secrets

from .config import config

try:
    from coincurve import PrivateKey
    HAS_COINCURVE = True
except ImportError:
    HAS_COINCURVE = False


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _ripemd160(data: bytes) -> bytes:
    h = hashlib.new("ripemd160")
    h.update(data)
    return h.digest()


def _hash160(data: bytes) -> bytes:
    return _ripemd160(_sha256(data))


def _base58check_encode(payload: bytes) -> str:
    """Base58Check encoding for Bitcoin addresses."""
    alphabet = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    checksum = _sha256(_sha256(payload))[:4]
    data = payload + checksum
    # Convert to integer
    n = int.from_bytes(data, "big")
    result = []
    while n > 0:
        n, remainder = divmod(n, 58)
        result.append(alphabet[remainder:remainder + 1])
    # Add leading 1s for each leading zero byte
    for byte in data:
        if byte == 0:
            result.append(b"1")
        else:
            break
    return b"".join(reversed(result)).decode("ascii")


def privkey_to_address(privkey_int: int) -> str:
    """Convert a private key integer to a compressed Bitcoin P2PKH address."""
    privkey_bytes = privkey_int.to_bytes(32, "big")
    if HAS_COINCURVE:
        pk = PrivateKey(privkey_bytes)
        pubkey = pk.public_key.format(compressed=True)
    else:
        # Fallback: pure Python secp256k1 (slow, for testing only)
        pubkey = _pure_python_pubkey(privkey_int)
    h160 = _hash160(pubkey)
    # Version byte 0x00 for mainnet
    return _base58check_encode(b"\x00" + h160)


def _pure_python_pubkey(privkey_int: int) -> bytes:
    """Pure Python secp256k1 point multiplication (SLOW - fallback only)."""
    p = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
    Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
    Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8

    def modinv(a, m):
        g, x, _ = _extended_gcd(a % m, m)
        return x % m

    def _extended_gcd(a, b):
        if a == 0:
            return b, 0, 1
        g, x, y = _extended_gcd(b % a, a)
        return g, y - (b // a) * x, x

    def point_add(P, Q):
        if P is None:
            return Q
        if Q is None:
            return P
        x1, y1 = P
        x2, y2 = Q
        if x1 == x2 and y1 != y2:
            return None
        if x1 == x2:
            lam = (3 * x1 * x1) * modinv(2 * y1, p) % p
        else:
            lam = (y2 - y1) * modinv(x2 - x1, p) % p
        x3 = (lam * lam - x1 - x2) % p
        y3 = (lam * (x1 - x3) - y1) % p
        return (x3, y3)

    def point_mul(k, P):
        R = None
        while k > 0:
            if k & 1:
                R = point_add(R, P)
            P = point_add(P, P)
            k >>= 1
        return R

    G = (Gx, Gy)
    pub = point_mul(privkey_int, G)
    x, y = pub
    prefix = b"\x02" if y % 2 == 0 else b"\x03"
    return prefix + x.to_bytes(32, "big")


class CanaryGenerator:
    def __init__(self):
        self._count = config.server.canaries_per_chunk

    def generate(self, range_start: int, range_end: int) -> list[dict]:
        """Generate canary keys uniformly spread within a range.

        Returns list of {privkey_hex, address}.
        """
        canaries = []
        span = range_end - range_start
        for i in range(self._count):
            # Spread canaries across the range
            segment_size = span // self._count
            seg_start = range_start + i * segment_size
            seg_end = seg_start + segment_size - 1
            privkey_int = secrets.randbelow(seg_end - seg_start) + seg_start
            address = privkey_to_address(privkey_int)
            canaries.append({
                "privkey_hex": hex(privkey_int),
                "address": address,
            })
        return canaries

    def verify(self, canaries: list[dict], reported_keys: dict[str, str]) -> tuple[bool, int]:
        """Verify worker-reported canary keys.

        Args:
            canaries: Original canary data [{privkey_hex, address}, ...]
            reported_keys: {address: privkey_hex} from worker

        Returns:
            (all_passed, failures_count)
        """
        failures = 0
        for canary in canaries:
            address = canary["address"]
            expected_privkey = canary["privkey_hex"]
            reported = reported_keys.get(address)
            if reported is None:
                failures += 1
                continue
            # Verify the reported private key produces the correct address
            try:
                reported_int = int(reported, 16)
                computed_address = privkey_to_address(reported_int)
                if computed_address != address:
                    failures += 1
            except (ValueError, Exception):
                failures += 1

        return failures == 0, failures
