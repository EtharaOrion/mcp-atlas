from fastmcp import FastMCP
import base64
import codecs
import html
import quopri
import binascii
from urllib.parse import quote, unquote
from typing import Dict

mcp = FastMCP("EncodingServer")


MORSE_TABLE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.", "!": "-.-.--",
    "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...", ":": "---...",
    ";": "-.-.-.", "=": "-...-", "+": ".-.-.", "-": "-....-", "_": "..--.-",
    "\"": ".-..-.", "$": "...-..-", "@": ".--.-.", " ": "/",
}
MORSE_REVERSE = {v: k for k, v in MORSE_TABLE.items()}


@mcp.tool
async def base64_encode(text: str) -> str:
    """Encode `text` as standard Base64."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


@mcp.tool
async def base64_decode(data: str) -> str:
    """Decode a standard Base64 string back to text."""
    return base64.b64decode(data.encode("ascii")).decode("utf-8")


@mcp.tool
async def base64url_encode(text: str) -> str:
    """Encode `text` as URL-safe Base64 (no '+' or '/')."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


@mcp.tool
async def base64url_decode(data: str) -> str:
    """Decode a URL-safe Base64 string back to text."""
    return base64.urlsafe_b64decode(data.encode("ascii")).decode("utf-8")


@mcp.tool
async def base32_encode(text: str) -> str:
    """Encode `text` as Base32."""
    return base64.b32encode(text.encode("utf-8")).decode("ascii")


@mcp.tool
async def base32_decode(data: str) -> str:
    """Decode a Base32 string back to text."""
    return base64.b32decode(data.encode("ascii")).decode("utf-8")


@mcp.tool
async def base16_encode(text: str) -> str:
    """Encode `text` as Base16 (uppercase hex)."""
    return base64.b16encode(text.encode("utf-8")).decode("ascii")


@mcp.tool
async def base16_decode(data: str) -> str:
    """Decode a Base16 (hex) string back to text."""
    return base64.b16decode(data.encode("ascii"), casefold=True).decode("utf-8")


@mcp.tool
async def url_encode(text: str, safe: str = "") -> str:
    """Percent-encode `text` for use in a URL (RFC 3986)."""
    return quote(text, safe=safe)


@mcp.tool
async def url_decode(text: str) -> str:
    """Decode a percent-encoded URL string."""
    return unquote(text)


@mcp.tool
async def hex_encode(text: str) -> str:
    """Encode `text` as a lowercase hex string."""
    return binascii.hexlify(text.encode("utf-8")).decode("ascii")


@mcp.tool
async def hex_decode(data: str) -> str:
    """Decode a hex string back to text."""
    return binascii.unhexlify(data.encode("ascii")).decode("utf-8")


@mcp.tool
async def rot13(text: str) -> str:
    """Apply ROT13 (self-inverse letter substitution) to `text`."""
    return codecs.encode(text, "rot_13")


@mcp.tool
async def rot_n(text: str, n: int = 13) -> str:
    """Apply a Caesar shift of `n` to alphabetic characters in `text`."""
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr((ord(ch) - 97 + n) % 26 + 97))
        elif "A" <= ch <= "Z":
            out.append(chr((ord(ch) - 65 + n) % 26 + 65))
        else:
            out.append(ch)
    return "".join(out)


@mcp.tool
async def quoted_printable_encode(text: str) -> str:
    """Encode `text` in RFC 2045 quoted-printable format."""
    return quopri.encodestring(text.encode("utf-8")).decode("ascii")


@mcp.tool
async def quoted_printable_decode(data: str) -> str:
    """Decode a quoted-printable string back to text."""
    return quopri.decodestring(data.encode("ascii")).decode("utf-8")


@mcp.tool
async def html_escape(text: str) -> str:
    """Escape HTML-special characters (& < > \" ') in `text`."""
    return html.escape(text, quote=True)


@mcp.tool
async def html_unescape(text: str) -> str:
    """Decode HTML entities in `text` back to their characters."""
    return html.unescape(text)


@mcp.tool
async def ascii85_encode(text: str) -> str:
    """Encode `text` in Ascii85 (no adobe framing)."""
    return base64.a85encode(text.encode("utf-8")).decode("ascii")


@mcp.tool
async def ascii85_decode(data: str) -> str:
    """Decode an Ascii85 string back to text."""
    return base64.a85decode(data.encode("ascii")).decode("utf-8")


@mcp.tool
async def utf8_bytes_hex(text: str) -> str:
    """Return the UTF-8 byte representation of `text` as a hex string."""
    return text.encode("utf-8").hex()


@mcp.tool
async def utf16_bytes_hex(text: str, byteorder: str = "little") -> str:
    """Return the UTF-16 byte representation of `text` as a hex string."""
    enc = "utf-16-le" if byteorder == "little" else "utf-16-be"
    return text.encode(enc).hex()


@mcp.tool
async def latin1_encode_hex(text: str) -> str:
    """Return `text` encoded as Latin-1 in hex (fails on non-latin1 code points)."""
    return text.encode("latin-1").hex()


@mcp.tool
async def latin1_decode_hex(data: str) -> str:
    """Decode a hex-encoded Latin-1 byte string back to text."""
    return bytes.fromhex(data).decode("latin-1")


@mcp.tool
async def morse_encode(text: str) -> str:
    """Encode ASCII `text` in International Morse code (letters separated by space)."""
    return " ".join(MORSE_TABLE.get(ch.upper(), "") for ch in text)


@mcp.tool
async def morse_decode(text: str) -> str:
    """Decode a space-separated Morse code string back to plain text."""
    return "".join(MORSE_REVERSE.get(sym, "") for sym in text.split(" "))


@mcp.tool
async def unicode_escape(text: str) -> str:
    """Return `text` with non-ASCII characters escaped as \\uXXXX."""
    return text.encode("unicode-escape").decode("ascii")


@mcp.tool
async def unicode_unescape(text: str) -> str:
    """Decode a string containing \\uXXXX escapes back to Unicode."""
    return text.encode("ascii").decode("unicode-escape")


@mcp.tool
async def punycode_encode(text: str) -> str:
    """Encode `text` as Punycode (RFC 3492, used for IDN hostnames)."""
    return text.encode("punycode").decode("ascii")


@mcp.tool
async def punycode_decode(data: str) -> str:
    """Decode a Punycode-encoded string back to text."""
    return data.encode("ascii").decode("punycode")


@mcp.tool
async def idna_encode(text: str) -> str:
    """Encode a Unicode domain label to ASCII (IDNA)."""
    return text.encode("idna").decode("ascii")


@mcp.tool
async def idna_decode(data: str) -> str:
    """Decode an ASCII (IDNA) domain label back to Unicode."""
    return data.encode("ascii").decode("idna")


@mcp.tool
async def detect_encoding(hex_bytes: str) -> Dict:
    """Heuristically report BOM/encoding of a hex-encoded byte sequence."""
    b = bytes.fromhex(hex_bytes)
    if b.startswith(b"\xef\xbb\xbf"):
        return {"encoding": "utf-8-sig", "bom": True}
    if b.startswith(b"\xff\xfe"):
        return {"encoding": "utf-16-le", "bom": True}
    if b.startswith(b"\xfe\xff"):
        return {"encoding": "utf-16-be", "bom": True}
    try:
        b.decode("utf-8")
        return {"encoding": "utf-8", "bom": False}
    except UnicodeDecodeError:
        return {"encoding": "latin-1", "bom": False}


@mcp.tool
async def is_valid_base64(data: str) -> bool:
    """Return True if `data` is a valid Base64 string."""
    try:
        base64.b64decode(data.encode("ascii"), validate=True)
        return True
    except (binascii.Error, ValueError):
        return False
