from fastmcp import FastMCP
from typing import Dict, List, Optional
import re

mcp = FastMCP("BarcodeServer")


QR_BYTE_CAPACITY: Dict[int, Dict[str, int]] = {
    1: {"L": 17, "M": 14, "Q": 11, "H": 7},
    2: {"L": 32, "M": 26, "Q": 20, "H": 14},
    3: {"L": 53, "M": 42, "Q": 32, "H": 24},
    4: {"L": 78, "M": 62, "Q": 46, "H": 34},
    5: {"L": 106, "M": 84, "Q": 60, "H": 44},
    6: {"L": 134, "M": 106, "Q": 74, "H": 58},
    7: {"L": 154, "M": 122, "Q": 86, "H": 64},
    8: {"L": 192, "M": 152, "Q": 108, "H": 84},
    9: {"L": 230, "M": 180, "Q": 130, "H": 98},
    10: {"L": 271, "M": 213, "Q": 151, "H": 119},
    15: {"L": 523, "M": 412, "Q": 292, "H": 220},
    20: {"L": 858, "M": 666, "Q": 482, "H": 382},
    25: {"L": 1273, "M": 991, "Q": 715, "H": 535},
    30: {"L": 1732, "M": 1354, "Q": 976, "H": 742},
    40: {"L": 2953, "M": 2331, "Q": 1663, "H": 1273},
}


def _only_digits(s: str) -> bool:
    return bool(s) and s.isdigit()


def _ean_checksum(digits: str, odd_mult: int, even_mult: int) -> int:
    total = 0
    for i, d in enumerate(digits):
        m = odd_mult if i % 2 == 0 else even_mult
        total += int(d) * m
    return (10 - total % 10) % 10


@mcp.tool
async def ean13_checksum(digits12: str) -> int:
    """Compute the EAN-13 check digit for a 12-digit prefix."""
    if len(digits12) != 12 or not _only_digits(digits12):
        raise ValueError("expected 12 digits")
    return _ean_checksum(digits12, odd_mult=1, even_mult=3)


@mcp.tool
async def ean13_validate(digits13: str) -> bool:
    """Return True if a 13-digit EAN-13 code has a valid check digit."""
    if len(digits13) != 13 or not _only_digits(digits13):
        return False
    return _ean_checksum(digits13[:12], 1, 3) == int(digits13[12])


@mcp.tool
async def ean13_generate(digits12: str) -> str:
    """Return the full 13-digit EAN-13 code built from a 12-digit prefix."""
    return digits12 + str(await ean13_checksum.__wrapped__(digits12))


@mcp.tool
async def ean8_checksum(digits7: str) -> int:
    """Compute the EAN-8 check digit for a 7-digit prefix."""
    if len(digits7) != 7 or not _only_digits(digits7):
        raise ValueError("expected 7 digits")
    return _ean_checksum(digits7, odd_mult=3, even_mult=1)


@mcp.tool
async def ean8_validate(digits8: str) -> bool:
    """Return True if an 8-digit EAN-8 code has a valid check digit."""
    if len(digits8) != 8 or not _only_digits(digits8):
        return False
    return _ean_checksum(digits8[:7], 3, 1) == int(digits8[7])


@mcp.tool
async def upc_checksum(digits11: str) -> int:
    """Compute the UPC-A check digit for an 11-digit prefix."""
    if len(digits11) != 11 or not _only_digits(digits11):
        raise ValueError("expected 11 digits")
    return _ean_checksum(digits11, odd_mult=3, even_mult=1)


@mcp.tool
async def upc_validate(digits12: str) -> bool:
    """Return True if a 12-digit UPC-A code has a valid check digit."""
    if len(digits12) != 12 or not _only_digits(digits12):
        return False
    return _ean_checksum(digits12[:11], 3, 1) == int(digits12[11])


@mcp.tool
async def upc_generate(digits11: str) -> str:
    """Return the full 12-digit UPC-A code built from an 11-digit prefix."""
    return digits11 + str(await upc_checksum.__wrapped__(digits11))


@mcp.tool
async def isbn10_checksum(digits9: str) -> str:
    """Compute the ISBN-10 check digit (may be 'X') for a 9-digit prefix."""
    if len(digits9) != 9 or not _only_digits(digits9):
        raise ValueError("expected 9 digits")
    total = sum(int(d) * (10 - i) for i, d in enumerate(digits9))
    cd = (11 - total % 11) % 11
    return "X" if cd == 10 else str(cd)


@mcp.tool
async def isbn10_validate(isbn: str) -> bool:
    """Return True if a 10-character ISBN-10 (with optional 'X' check) is valid."""
    isbn = isbn.replace("-", "").replace(" ", "").upper()
    if len(isbn) != 10 or not (isbn[:9].isdigit() and (isbn[9].isdigit() or isbn[9] == "X")):
        return False
    total = sum(int(d) * (10 - i) for i, d in enumerate(isbn[:9]))
    check = 10 if isbn[9] == "X" else int(isbn[9])
    return (total + check) % 11 == 0


@mcp.tool
async def isbn13_checksum(digits12: str) -> int:
    """Compute the ISBN-13 check digit (identical algorithm to EAN-13)."""
    return await ean13_checksum.__wrapped__(digits12)


@mcp.tool
async def isbn13_validate(isbn: str) -> bool:
    """Return True if a 13-digit ISBN-13 has a valid check digit."""
    return await ean13_validate.__wrapped__(isbn.replace("-", "").replace(" ", ""))


@mcp.tool
async def isbn10_to_isbn13(isbn10: str) -> str:
    """Convert a valid ISBN-10 to its ISBN-13 equivalent (978 prefix)."""
    isbn10 = isbn10.replace("-", "").replace(" ", "").upper()
    if len(isbn10) != 10:
        raise ValueError("expected 10-char ISBN-10")
    prefix = "978" + isbn10[:9]
    return prefix + str(await ean13_checksum.__wrapped__(prefix))


@mcp.tool
async def code128_validate(text: str) -> bool:
    """Return True if `text` uses only characters valid for Code 128 (ASCII 0-127)."""
    return all(0 <= ord(c) <= 127 for c in text)


@mcp.tool
async def code128_length(text: str) -> int:
    """Return the encoded symbol length (chars) that Code 128 would use for `text`."""
    return len(text)


@mcp.tool
async def luhn_checksum(digits: str) -> int:
    """Compute the Luhn check digit for a numeric string (used by credit cards)."""
    if not _only_digits(digits):
        raise ValueError("digits must be numeric")
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10


@mcp.tool
async def luhn_validate(digits: str) -> bool:
    """Return True if `digits` passes the Luhn checksum (credit-card style)."""
    if not _only_digits(digits) or len(digits) < 2:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


@mcp.tool
async def gtin14_checksum(digits13: str) -> int:
    """Compute the GTIN-14 check digit for a 13-digit prefix."""
    if len(digits13) != 13 or not _only_digits(digits13):
        raise ValueError("expected 13 digits")
    total = 0
    for i, d in enumerate(digits13):
        m = 3 if (len(digits13) - i) % 2 == 1 else 1
        total += int(d) * m
    return (10 - total % 10) % 10


@mcp.tool
async def gtin14_validate(digits14: str) -> bool:
    """Return True if a 14-digit GTIN-14 code has a valid check digit."""
    if len(digits14) != 14 or not _only_digits(digits14):
        return False
    return await gtin14_checksum.__wrapped__(digits14[:13]) == int(digits14[13])


@mcp.tool
async def barcode_type_detect(digits: str) -> str:
    """Guess the barcode type by digit length (ean8, upc, ean13, gtin14, unknown)."""
    clean = digits.replace("-", "").replace(" ", "")
    if not clean.isdigit():
        return "unknown"
    return {8: "ean8", 12: "upc", 13: "ean13", 14: "gtin14"}.get(len(clean), "unknown")


@mcp.tool
async def qr_data_capacity(version: int, ecc_level: str = "M") -> int:
    """Return the max byte-mode data capacity for a given QR version and ECC level (L/M/Q/H)."""
    if version not in QR_BYTE_CAPACITY:
        raise ValueError(f"version {version} not in capacity table")
    lvl = ecc_level.upper()
    if lvl not in QR_BYTE_CAPACITY[version]:
        raise ValueError("ecc_level must be L, M, Q, or H")
    return QR_BYTE_CAPACITY[version][lvl]


@mcp.tool
async def qr_recommend_version(text: str, ecc_level: str = "M") -> Optional[int]:
    """Return the smallest QR version that fits `text` at the requested ECC level."""
    n = len(text.encode("utf-8"))
    lvl = ecc_level.upper()
    for v in sorted(QR_BYTE_CAPACITY.keys()):
        if QR_BYTE_CAPACITY[v].get(lvl, 0) >= n:
            return v
    return None


@mcp.tool
async def qr_encode_text_meta(text: str, ecc_level: str = "M") -> Dict:
    """Return QR metadata for `text` (recommended version, mode, char/byte count). No image generated."""
    n = len(text.encode("utf-8"))
    mode = "byte"
    if re.fullmatch(r"[0-9]+", text):
        mode = "numeric"
    elif re.fullmatch(r"[0-9A-Z $%*+\-./:]+", text):
        mode = "alphanumeric"
    return {
        "chars": len(text),
        "bytes": n,
        "mode": mode,
        "ecc_level": ecc_level.upper(),
        "recommended_version": await qr_recommend_version.__wrapped__(text, ecc_level),
    }


@mcp.tool
async def format_barcode(digits: str, kind: str = "ean13") -> str:
    """Return a human-readable formatted barcode string, spacing by convention."""
    kind = kind.lower()
    if kind == "ean13" and len(digits) == 13:
        return f"{digits[0]} {digits[1:7]} {digits[7:]}"
    if kind == "upc" and len(digits) == 12:
        return f"{digits[0]} {digits[1:6]} {digits[6:11]} {digits[11]}"
    if kind == "isbn13" and len(digits) == 13:
        return f"{digits[:3]}-{digits[3]}-{digits[4:8]}-{digits[8:12]}-{digits[12]}"
    return digits
