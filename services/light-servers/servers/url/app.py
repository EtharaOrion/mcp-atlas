from fastmcp import FastMCP
from urllib.parse import (
    urlparse, urlunparse, urlencode, parse_qs, parse_qsl,
    quote, unquote, quote_plus, unquote_plus, urljoin,
)
from typing import Dict, List, Optional
import re

mcp = FastMCP("URLServer")


@mcp.tool
async def parse_url(url: str) -> Dict:
    """Parse a URL into its component parts (scheme, netloc, path, query, fragment)."""
    p = urlparse(url)
    return {
        "scheme": p.scheme,
        "netloc": p.netloc,
        "hostname": p.hostname or "",
        "port": p.port,
        "username": p.username or "",
        "password": p.password or "",
        "path": p.path,
        "params": p.params,
        "query": p.query,
        "fragment": p.fragment,
    }


@mcp.tool
async def build_url(
    scheme: str = "https",
    netloc: str = "",
    path: str = "",
    params: str = "",
    query: str = "",
    fragment: str = "",
) -> str:
    """Assemble a URL from parts using standard URL syntax."""
    return urlunparse((scheme, netloc, path, params, query, fragment))


@mcp.tool
async def validate(url: str) -> bool:
    """Return True if `url` has a non-empty scheme and netloc (RFC 3986 style)."""
    try:
        p = urlparse(url)
        return bool(p.scheme) and bool(p.netloc)
    except Exception:
        return False


@mcp.tool
async def extract_query(url: str) -> Dict[str, List[str]]:
    """Return a dict mapping query keys to a list of their values."""
    return parse_qs(urlparse(url).query)


@mcp.tool
async def extract_query_flat(url: str) -> Dict[str, str]:
    """Return a flat dict of query params (last value wins on duplicates)."""
    return dict(parse_qsl(urlparse(url).query))


@mcp.tool
async def add_query_param(url: str, key: str, value: str) -> str:
    """Return the URL with an additional query parameter appended."""
    p = urlparse(url)
    pairs = parse_qsl(p.query, keep_blank_values=True)
    pairs.append((key, value))
    return urlunparse(p._replace(query=urlencode(pairs)))


@mcp.tool
async def remove_query_param(url: str, key: str) -> str:
    """Return the URL with all instances of `key` removed from the query string."""
    p = urlparse(url)
    pairs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != key]
    return urlunparse(p._replace(query=urlencode(pairs)))


@mcp.tool
async def set_query_param(url: str, key: str, value: str) -> str:
    """Return the URL with `key` set to `value`, replacing any existing values."""
    p = urlparse(url)
    pairs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != key]
    pairs.append((key, value))
    return urlunparse(p._replace(query=urlencode(pairs)))


@mcp.tool
async def encode(text: str, safe: str = "/") -> str:
    """Percent-encode `text` for use in a URL path (RFC 3986)."""
    return quote(text, safe=safe)


@mcp.tool
async def decode(text: str) -> str:
    """Percent-decode a URL-encoded string."""
    return unquote(text)


@mcp.tool
async def encode_plus(text: str) -> str:
    """Percent-encode `text` for a query string (spaces become '+')."""
    return quote_plus(text)


@mcp.tool
async def decode_plus(text: str) -> str:
    """Decode a query-string-style percent-encoded value ('+' becomes space)."""
    return unquote_plus(text)


@mcp.tool
async def join_url(base: str, ref: str) -> str:
    """Resolve a possibly-relative `ref` URL against `base`, returning the absolute URL."""
    return urljoin(base, ref)


@mcp.tool
async def domain(url: str) -> str:
    """Return the hostname of `url` (no port, no userinfo)."""
    return urlparse(url).hostname or ""


@mcp.tool
async def extract_path(url: str) -> str:
    """Return the path component of `url`."""
    return urlparse(url).path


@mcp.tool
async def extract_scheme(url: str) -> str:
    """Return the scheme component of `url` (e.g. https, ftp)."""
    return urlparse(url).scheme


@mcp.tool
async def extract_port(url: str) -> Optional[int]:
    """Return the port of `url` or None if not specified."""
    return urlparse(url).port


@mcp.tool
async def is_absolute(url: str) -> bool:
    """Return True if `url` has both scheme and netloc."""
    p = urlparse(url)
    return bool(p.scheme) and bool(p.netloc)


@mcp.tool
async def strip_query(url: str) -> str:
    """Return `url` with the query string removed."""
    p = urlparse(url)
    return urlunparse(p._replace(query=""))


@mcp.tool
async def strip_fragment(url: str) -> str:
    """Return `url` with the fragment removed."""
    p = urlparse(url)
    return urlunparse(p._replace(fragment=""))


@mcp.tool
async def normalize(url: str) -> str:
    """Normalize `url` by lowercasing scheme/host and stripping default ports (80/443)."""
    p = urlparse(url)
    scheme = (p.scheme or "").lower()
    netloc = (p.hostname or "").lower()
    if p.port and not (
        (scheme == "http" and p.port == 80) or (scheme == "https" and p.port == 443)
    ):
        netloc = f"{netloc}:{p.port}"
    path = p.path or "/"
    return urlunparse((scheme, netloc, path, p.params, p.query, p.fragment))


@mcp.tool
async def extract_extension(url: str) -> str:
    """Return the file extension of the last path segment (empty string if none)."""
    path = urlparse(url).path
    m = re.search(r"\.([^./?#]+)$", path)
    return m.group(1) if m else ""


@mcp.tool
async def split_domain(url: str) -> Dict[str, str]:
    """Split the hostname of `url` into subdomain / domain / tld heuristically."""
    host = urlparse(url).hostname or ""
    parts = host.split(".")
    if len(parts) < 2:
        return {"subdomain": "", "domain": host, "tld": ""}
    tld = parts[-1]
    domain_ = parts[-2]
    subdomain = ".".join(parts[:-2])
    return {"subdomain": subdomain, "domain": domain_, "tld": tld}


@mcp.tool
async def to_ascii(url: str) -> str:
    """Convert `url` to ASCII/punycode form (for IDN hostnames)."""
    p = urlparse(url)
    host = p.hostname or ""
    try:
        ascii_host = host.encode("idna").decode("ascii") if host else ""
    except Exception:
        ascii_host = host
    if p.port:
        ascii_host = f"{ascii_host}:{p.port}"
    return urlunparse(p._replace(netloc=ascii_host))


@mcp.tool
async def to_unicode(url: str) -> str:
    """Convert punycode hostname to its Unicode form if applicable."""
    p = urlparse(url)
    host = p.hostname or ""
    try:
        uni = host.encode("ascii").decode("idna") if host else ""
    except Exception:
        uni = host
    if p.port:
        uni = f"{uni}:{p.port}"
    return urlunparse(p._replace(netloc=uni))


@mcp.tool
async def dict_to_query(params: Dict[str, str]) -> str:
    """Encode a dict of key/value pairs as a query string."""
    return urlencode(params)


@mcp.tool
async def query_to_dict(query: str) -> Dict[str, str]:
    """Parse a raw query string (no leading '?') into a flat dict."""
    return dict(parse_qsl(query, keep_blank_values=True))
