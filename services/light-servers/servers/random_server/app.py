from fastmcp import FastMCP
import random
import secrets
import string
import uuid
import time
from typing import List, Optional

mcp = FastMCP("RandomServer")


FIRST_NAMES_M = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles"]
FIRST_NAMES_F = ["Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez"]
WORDS = ["ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing", "elit", "sed", "eiusmod",
         "tempor", "incididunt", "labore", "magna", "aliqua", "veniam", "nostrud", "ullamco",
         "laboris", "aliquip", "commodo", "consequat", "duis", "aute", "irure", "reprehenderit",
         "voluptate", "velit", "esse", "cillum", "fugiat", "nulla", "pariatur", "excepteur",
         "occaecat", "cupidatat", "proident", "sunt", "culpa", "officia", "deserunt", "mollit"]
DOMAINS = ["example.com", "test.org", "sample.net", "demo.io", "acme.co", "widgets.dev"]


def _rng(seed: Optional[int]) -> random.Random:
    return random.Random(seed) if seed is not None else random.Random()


@mcp.tool
async def int_between(low: int, high: int, seed: Optional[int] = None) -> int:
    """Return a uniformly-random integer in [low, high] inclusive. Deterministic if `seed` given."""
    return _rng(seed).randint(low, high)


@mcp.tool
async def float_between(low: float, high: float, seed: Optional[int] = None) -> float:
    """Return a uniformly-random float in [low, high]. Deterministic if `seed` given."""
    return _rng(seed).uniform(low, high)


@mcp.tool
async def gaussian(mean: float = 0.0, stddev: float = 1.0, seed: Optional[int] = None) -> float:
    """Return a sample from a Gaussian distribution with the given `mean` and `stddev`."""
    return _rng(seed).gauss(mean, stddev)


@mcp.tool
async def exponential(rate: float = 1.0, seed: Optional[int] = None) -> float:
    """Return a sample from an exponential distribution with the given rate parameter."""
    return _rng(seed).expovariate(rate)


@mcp.tool
async def boolean(p_true: float = 0.5, seed: Optional[int] = None) -> bool:
    """Return True with probability `p_true`, else False."""
    return _rng(seed).random() < p_true


@mcp.tool
async def choice(seq: List, seed: Optional[int] = None):
    """Return one uniformly-random element from `seq`."""
    if not seq:
        raise ValueError("seq must not be empty")
    return _rng(seed).choice(seq)


@mcp.tool
async def choices(seq: List, k: int = 1, weights: Optional[List[float]] = None, seed: Optional[int] = None) -> List:
    """Return `k` elements drawn with replacement from `seq`, optionally weighted."""
    return _rng(seed).choices(seq, weights=weights, k=k)


@mcp.tool
async def sample(seq: List, k: int, seed: Optional[int] = None) -> List:
    """Return `k` elements drawn without replacement from `seq`."""
    return _rng(seed).sample(seq, k)


@mcp.tool
async def shuffle(seq: List, seed: Optional[int] = None) -> List:
    """Return a copy of `seq` shuffled uniformly at random."""
    out = list(seq)
    _rng(seed).shuffle(out)
    return out


@mcp.tool
async def uuid4(seed: Optional[int] = None) -> str:
    """Return a UUID4 string. If `seed` is given, uses a seeded RNG (deterministic)."""
    if seed is None:
        return str(uuid.uuid4())
    r = _rng(seed)
    return str(uuid.UUID(int=r.getrandbits(128), version=4))


@mcp.tool
async def uuid7() -> str:
    """Return a time-ordered UUIDv7-style string (48-bit ms timestamp + random)."""
    ts = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    hi = (ts << 16) | (0x7 << 12) | rand_a
    lo = (0b10 << 62) | rand_b
    val = (hi << 64) | lo
    return str(uuid.UUID(int=val))


@mcp.tool
async def name(gender: str = "any", seed: Optional[int] = None) -> str:
    """Return a first+last name. `gender` may be 'm', 'f', or 'any'."""
    r = _rng(seed)
    if gender == "m":
        first = r.choice(FIRST_NAMES_M)
    elif gender == "f":
        first = r.choice(FIRST_NAMES_F)
    else:
        first = r.choice(FIRST_NAMES_M + FIRST_NAMES_F)
    return f"{first} {r.choice(LAST_NAMES)}"


@mcp.tool
async def word(seed: Optional[int] = None) -> str:
    """Return a single lorem-ipsum-style word."""
    return _rng(seed).choice(WORDS)


@mcp.tool
async def sentence(n_words: int = 8, seed: Optional[int] = None) -> str:
    """Return a lorem-ipsum sentence of roughly `n_words` words, capitalized and punctuated."""
    r = _rng(seed)
    words = [r.choice(WORDS) for _ in range(max(1, n_words))]
    words[0] = words[0].capitalize()
    return " ".join(words) + "."


@mcp.tool
async def paragraph(n_sentences: int = 4, seed: Optional[int] = None) -> str:
    """Return a lorem-ipsum paragraph of `n_sentences` sentences."""
    r = _rng(seed)
    sentences = []
    for _ in range(max(1, n_sentences)):
        n = r.randint(6, 14)
        words = [r.choice(WORDS) for _ in range(n)]
        words[0] = words[0].capitalize()
        sentences.append(" ".join(words) + ".")
    return " ".join(sentences)


@mcp.tool
async def lorem(n_words: int = 50, seed: Optional[int] = None) -> str:
    """Return `n_words` lorem-ipsum words (no capitalization or punctuation)."""
    r = _rng(seed)
    return " ".join(r.choice(WORDS) for _ in range(n_words))


@mcp.tool
async def password(length: int = 16, use_symbols: bool = True, seed: Optional[int] = None) -> str:
    """Return a random password of the given `length`. `seed` makes it deterministic."""
    r = _rng(seed)
    alphabet = string.ascii_letters + string.digits
    if use_symbols:
        alphabet += "!@#$%^&*()-_=+"
    return "".join(r.choice(alphabet) for _ in range(length))


@mcp.tool
async def token_hex(nbytes: int = 16) -> str:
    """Return a cryptographically secure hex token of `nbytes` bytes."""
    return secrets.token_hex(nbytes)


@mcp.tool
async def token_urlsafe(nbytes: int = 32) -> str:
    """Return a cryptographically secure URL-safe token of approximately `nbytes` bytes of entropy."""
    return secrets.token_urlsafe(nbytes)


@mcp.tool
async def email(seed: Optional[int] = None) -> str:
    """Return a fake email address using the seeded RNG."""
    r = _rng(seed)
    user = f"{r.choice(FIRST_NAMES_M + FIRST_NAMES_F).lower()}.{r.choice(LAST_NAMES).lower()}"
    return f"{user}@{r.choice(DOMAINS)}"


@mcp.tool
async def phone(seed: Optional[int] = None) -> str:
    """Return a fake North American 10-digit phone number formatted as (XXX) XXX-XXXX."""
    r = _rng(seed)
    area = r.randint(200, 999)
    prefix = r.randint(200, 999)
    line = r.randint(0, 9999)
    return f"({area}) {prefix}-{line:04d}"


@mcp.tool
async def date_between(start: str = "2020-01-01", end: str = "2026-12-31", seed: Optional[int] = None) -> str:
    """Return a random ISO date string between `start` and `end` (YYYY-MM-DD)."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    delta = (d1 - d0).days
    r = _rng(seed)
    return (d0 + timedelta(days=r.randint(0, max(0, delta)))).isoformat()


@mcp.tool
async def weighted_choice(seq: List, weights: List[float], seed: Optional[int] = None):
    """Return a single element from `seq` sampled proportionally to `weights`."""
    return _rng(seed).choices(seq, weights=weights, k=1)[0]


@mcp.tool
async def dice(sides: int = 6, count: int = 1, seed: Optional[int] = None) -> List[int]:
    """Roll `count` dice with `sides` faces each. Returns the roll results."""
    r = _rng(seed)
    return [r.randint(1, sides) for _ in range(count)]


@mcp.tool
async def color_hex(seed: Optional[int] = None) -> str:
    """Return a random RGB hex color like #A1B2C3."""
    r = _rng(seed)
    return "#{:06X}".format(r.randint(0, 0xFFFFFF))


@mcp.tool
async def ip_v4(seed: Optional[int] = None) -> str:
    """Return a random IPv4 address string."""
    r = _rng(seed)
    return ".".join(str(r.randint(0, 255)) for _ in range(4))
