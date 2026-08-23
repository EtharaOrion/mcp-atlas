from fastmcp import FastMCP
import hashlib
import hmac
import zlib
import binascii
import os
import math
from typing import Dict, List

mcp = FastMCP("HashServer")


@mcp.tool
async def md5(text: str) -> str:
    """Return the MD5 hex digest of `text`."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


@mcp.tool
async def sha1(text: str) -> str:
    """Return the SHA-1 hex digest of `text`."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


@mcp.tool
async def sha256(text: str) -> str:
    """Return the SHA-256 hex digest of `text`."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@mcp.tool
async def sha512(text: str) -> str:
    """Return the SHA-512 hex digest of `text`."""
    return hashlib.sha512(text.encode("utf-8")).hexdigest()


@mcp.tool
async def sha3_256(text: str) -> str:
    """Return the SHA3-256 hex digest of `text`."""
    return hashlib.sha3_256(text.encode("utf-8")).hexdigest()


@mcp.tool
async def sha3_512(text: str) -> str:
    """Return the SHA3-512 hex digest of `text`."""
    return hashlib.sha3_512(text.encode("utf-8")).hexdigest()


@mcp.tool
async def blake2b(text: str, digest_size: int = 64) -> str:
    """Return the BLAKE2b hex digest of `text` with the given digest size (bytes)."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=digest_size).hexdigest()


@mcp.tool
async def blake2s(text: str, digest_size: int = 32) -> str:
    """Return the BLAKE2s hex digest of `text` with the given digest size (bytes)."""
    return hashlib.blake2s(text.encode("utf-8"), digest_size=digest_size).hexdigest()


@mcp.tool
async def checksum(text: str, algo: str = "sha256") -> str:
    """Return the hex digest of `text` computed with the named hash `algo`."""
    h = hashlib.new(algo)
    h.update(text.encode("utf-8"))
    return h.hexdigest()


@mcp.tool
async def checksum_file(path: str, algo: str = "sha256") -> str:
    """Compute the hex digest of the file at `path` using `algo`, streaming in 8KiB chunks."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


@mcp.tool
async def multi_hash(text: str) -> Dict[str, str]:
    """Return a dict of common hex digests (md5, sha1, sha256, sha512, blake2b) for `text`."""
    b = text.encode("utf-8")
    return {
        "md5": hashlib.md5(b).hexdigest(),
        "sha1": hashlib.sha1(b).hexdigest(),
        "sha256": hashlib.sha256(b).hexdigest(),
        "sha512": hashlib.sha512(b).hexdigest(),
        "blake2b": hashlib.blake2b(b).hexdigest(),
    }


@mcp.tool
async def hmac_sha256(key: str, message: str) -> str:
    """Return HMAC-SHA256(key, message) as a hex string."""
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


@mcp.tool
async def hmac_sha512(key: str, message: str) -> str:
    """Return HMAC-SHA512(key, message) as a hex string."""
    return hmac.new(key.encode(), message.encode(), hashlib.sha512).hexdigest()


@mcp.tool
async def hmac_verify(key: str, message: str, signature: str, algo: str = "sha256") -> bool:
    """Timing-safe verification that `signature` equals HMAC-<algo>(key, message)."""
    expected = hmac.new(key.encode(), message.encode(), getattr(hashlib, algo)).hexdigest()
    return hmac.compare_digest(expected, signature)


@mcp.tool
async def available_algorithms() -> List[str]:
    """Return the list of hash algorithm names guaranteed available in this environment."""
    return sorted(hashlib.algorithms_guaranteed)


@mcp.tool
async def crc32(text: str) -> int:
    """Return the CRC-32 checksum of `text` (unsigned 32-bit integer)."""
    return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF


@mcp.tool
async def adler32(text: str) -> int:
    """Return the Adler-32 checksum of `text`."""
    return zlib.adler32(text.encode("utf-8")) & 0xFFFFFFFF


@mcp.tool
async def fnv1a_32(text: str) -> int:
    """Return the 32-bit FNV-1a hash of `text`."""
    h = 0x811C9DC5
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


@mcp.tool
async def fnv1a_64(text: str) -> int:
    """Return the 64-bit FNV-1a hash of `text`."""
    h = 0xCBF29CE484222325
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


@mcp.tool
async def djb2(text: str) -> int:
    """Return the DJB2 hash of `text` (32-bit range)."""
    h = 5381
    for byte in text.encode("utf-8"):
        h = ((h << 5) + h + byte) & 0xFFFFFFFF
    return h


@mcp.tool
async def bloom_positions(text: str, m: int = 1024, k: int = 4) -> List[int]:
    """Return the `k` bit positions (mod `m`) that `text` would set in a Bloom filter.

    Stateless: caller can maintain the actual bit array. Uses SHA-256 slices as k hash functions.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    positions: List[int] = []
    for i in range(k):
        chunk = digest[(i * 4) % len(digest):(i * 4) % len(digest) + 4]
        if len(chunk) < 4:
            chunk = (chunk + digest)[:4]
        val = int.from_bytes(chunk, "big")
        positions.append(val % m)
    return positions


@mcp.tool
async def pbkdf2(password: str, salt: str, iterations: int = 100000, dklen: int = 32, algo: str = "sha256") -> str:
    """Derive a key from `password`+`salt` using PBKDF2. Returns hex-encoded key."""
    dk = hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), iterations, dklen)
    return binascii.hexlify(dk).decode()


@mcp.tool
async def scrypt_hex(password: str, salt: str, n: int = 16384, r: int = 8, p: int = 1, dklen: int = 32) -> str:
    """Derive a key from `password`+`salt` using scrypt. Returns hex-encoded key."""
    dk = hashlib.scrypt(password.encode(), salt=salt.encode(), n=n, r=r, p=p, dklen=dklen)
    return binascii.hexlify(dk).decode()


@mcp.tool
async def shannon_entropy(text: str) -> float:
    """Return the Shannon entropy (bits per character) of `text`."""
    if not text:
        return 0.0
    counts: Dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


@mcp.tool
async def hamming_distance_hex(hex_a: str, hex_b: str) -> int:
    """Bitwise Hamming distance between two equal-length hex strings."""
    a = binascii.unhexlify(hex_a)
    b = binascii.unhexlify(hex_b)
    if len(a) != len(b):
        raise ValueError("hex strings must have equal byte length")
    return sum(bin(x ^ y).count("1") for x, y in zip(a, b))


@mcp.tool
async def rolling_hash(text: str, window: int = 4, mod: int = 2**32 - 5) -> List[int]:
    """Return the rolling polynomial hash of every window of size `window` in `text`."""
    if window <= 0 or window > len(text):
        return []
    base = 257
    out: List[int] = []
    h = 0
    power = pow(base, window - 1, mod)
    b = text.encode("utf-8")
    for i in range(window):
        h = (h * base + b[i]) % mod
    out.append(h)
    for i in range(window, len(b)):
        h = ((h - b[i - window] * power) * base + b[i]) % mod
        out.append(h)
    return out


@mcp.tool
async def compare_hashes(a: str, b: str) -> bool:
    """Timing-safe equality check between two hex-encoded hash strings."""
    return hmac.compare_digest(a, b)
