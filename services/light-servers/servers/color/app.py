from fastmcp import FastMCP
import colorsys
import math
from typing import Dict, List, Tuple

mcp = FastMCP("ColorServer")


NAMED_COLORS: Dict[str, str] = {
    "black": "#000000", "white": "#FFFFFF", "red": "#FF0000", "green": "#008000",
    "blue": "#0000FF", "yellow": "#FFFF00", "cyan": "#00FFFF", "magenta": "#FF00FF",
    "silver": "#C0C0C0", "gray": "#808080", "maroon": "#800000", "olive": "#808000",
    "lime": "#00FF00", "aqua": "#00FFFF", "teal": "#008080", "navy": "#000080",
    "fuchsia": "#FF00FF", "purple": "#800080", "orange": "#FFA500", "pink": "#FFC0CB",
}


def _norm_hex(h: str) -> str:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"invalid hex color: {h}")
    return h.upper()


def _hex_to_rgb_tuple(h: str) -> Tuple[int, int, int]:
    h = _norm_hex(h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex_str(r: int, g: int, b: int) -> str:
    return "#{:02X}{:02X}{:02X}".format(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def _lum_channel(c: int) -> float:
    v = c / 255.0
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


@mcp.tool
async def hex_to_rgb(hex_str: str) -> List[int]:
    """Convert a #RRGGBB (or #RGB) hex color to a list [R, G, B] with 0-255 values."""
    return list(_hex_to_rgb_tuple(hex_str))


@mcp.tool
async def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert R, G, B in 0-255 to a #RRGGBB hex string."""
    return _rgb_to_hex_str(r, g, b)


@mcp.tool
async def hex_to_hsl(hex_str: str) -> List[float]:
    """Convert hex to [H, S, L] in ranges [0,360], [0,1], [0,1]."""
    r, g, b = _hex_to_rgb_tuple(hex_str)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return [h * 360, s, l]


@mcp.tool
async def hsl_to_hex(h: float, s: float, l: float) -> str:
    """Convert HSL to hex. H in [0,360], S/L in [0,1]."""
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, l, s)
    return _rgb_to_hex_str(int(r * 255), int(g * 255), int(b * 255))


@mcp.tool
async def hex_to_hsv(hex_str: str) -> List[float]:
    """Convert hex to [H, S, V] in ranges [0,360], [0,1], [0,1]."""
    r, g, b = _hex_to_rgb_tuple(hex_str)
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return [h * 360, s, v]


@mcp.tool
async def hsv_to_hex(h: float, s: float, v: float) -> str:
    """Convert HSV to hex. H in [0,360], S/V in [0,1]."""
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360, s, v)
    return _rgb_to_hex_str(int(r * 255), int(g * 255), int(b * 255))


@mcp.tool
async def rgb_to_hsl(r: int, g: int, b: int) -> List[float]:
    """Convert RGB (0-255) to [H, S, L]."""
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return [h * 360, s, l]


@mcp.tool
async def rgb_to_hsv(r: int, g: int, b: int) -> List[float]:
    """Convert RGB (0-255) to [H, S, V]."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return [h * 360, s, v]


@mcp.tool
async def relative_luminance(hex_str: str) -> float:
    """Return WCAG relative luminance of `hex_str` in [0,1]."""
    r, g, b = _hex_to_rgb_tuple(hex_str)
    return 0.2126 * _lum_channel(r) + 0.7152 * _lum_channel(g) + 0.0722 * _lum_channel(b)


@mcp.tool
async def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """Return the WCAG contrast ratio between two colors (1.0 to 21.0)."""
    la = await relative_luminance.__wrapped__(hex_a)
    lb = await relative_luminance.__wrapped__(hex_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@mcp.tool
async def wcag_check(hex_fg: str, hex_bg: str) -> Dict[str, bool]:
    """Report which WCAG levels the fg/bg pair passes: AA/AAA for normal/large text."""
    ratio = await contrast_ratio.__wrapped__(hex_fg, hex_bg)
    return {
        "ratio": ratio,
        "AA_normal": ratio >= 4.5,
        "AA_large": ratio >= 3.0,
        "AAA_normal": ratio >= 7.0,
        "AAA_large": ratio >= 4.5,
    }


@mcp.tool
async def lighten(hex_str: str, amount: float = 0.1) -> str:
    """Return `hex_str` lightened by `amount` (0-1) in HSL space."""
    h, s, l = await hex_to_hsl.__wrapped__(hex_str)
    return await hsl_to_hex.__wrapped__(h, s, min(1.0, l + amount))


@mcp.tool
async def darken(hex_str: str, amount: float = 0.1) -> str:
    """Return `hex_str` darkened by `amount` (0-1) in HSL space."""
    h, s, l = await hex_to_hsl.__wrapped__(hex_str)
    return await hsl_to_hex.__wrapped__(h, s, max(0.0, l - amount))


@mcp.tool
async def saturate(hex_str: str, amount: float = 0.1) -> str:
    """Return `hex_str` with saturation increased by `amount` (0-1) in HSL space."""
    h, s, l = await hex_to_hsl.__wrapped__(hex_str)
    return await hsl_to_hex.__wrapped__(h, min(1.0, s + amount), l)


@mcp.tool
async def desaturate(hex_str: str, amount: float = 0.1) -> str:
    """Return `hex_str` with saturation decreased by `amount` (0-1) in HSL space."""
    h, s, l = await hex_to_hsl.__wrapped__(hex_str)
    return await hsl_to_hex.__wrapped__(h, max(0.0, s - amount), l)


@mcp.tool
async def invert(hex_str: str) -> str:
    """Return the RGB inversion of `hex_str`."""
    r, g, b = _hex_to_rgb_tuple(hex_str)
    return _rgb_to_hex_str(255 - r, 255 - g, 255 - b)


@mcp.tool
async def complementary(hex_str: str) -> str:
    """Return the complementary color (hue rotated 180 degrees)."""
    h, s, l = await hex_to_hsl.__wrapped__(hex_str)
    return await hsl_to_hex.__wrapped__((h + 180) % 360, s, l)


@mcp.tool
async def triad(hex_str: str) -> List[str]:
    """Return a triadic color scheme (base + 2 hues 120 degrees apart)."""
    h, s, l = await hex_to_hsl.__wrapped__(hex_str)
    return [
        await hsl_to_hex.__wrapped__(h, s, l),
        await hsl_to_hex.__wrapped__((h + 120) % 360, s, l),
        await hsl_to_hex.__wrapped__((h + 240) % 360, s, l),
    ]


@mcp.tool
async def tetrad(hex_str: str) -> List[str]:
    """Return a tetradic color scheme (base + 3 hues 90 degrees apart)."""
    h, s, l = await hex_to_hsl.__wrapped__(hex_str)
    return [await hsl_to_hex.__wrapped__((h + i * 90) % 360, s, l) for i in range(4)]


@mcp.tool
async def analogous(hex_str: str, n: int = 5, spread: float = 30.0) -> List[str]:
    """Return `n` analogous colors spread across `spread` degrees of hue centered on the base."""
    h, s, l = await hex_to_hsl.__wrapped__(hex_str)
    if n <= 1:
        return [await hsl_to_hex.__wrapped__(h, s, l)]
    step = spread / (n - 1)
    start = h - spread / 2
    return [await hsl_to_hex.__wrapped__((start + i * step) % 360, s, l) for i in range(n)]


@mcp.tool
async def palette(hex_str: str, n: int = 5) -> List[str]:
    """Return a monochrome palette of `n` shades varying lightness from the base."""
    h, s, l = await hex_to_hsl.__wrapped__(hex_str)
    if n <= 1:
        return [await hsl_to_hex.__wrapped__(h, s, l)]
    step = 1.0 / (n + 1)
    return [await hsl_to_hex.__wrapped__(h, s, step * (i + 1)) for i in range(n)]


@mcp.tool
async def named_to_hex(name: str) -> str:
    """Look up a common CSS color name and return its hex value."""
    key = name.strip().lower()
    if key not in NAMED_COLORS:
        raise KeyError(f"unknown color name: {name}")
    return NAMED_COLORS[key]


@mcp.tool
async def distance(hex_a: str, hex_b: str) -> float:
    """Return the Euclidean distance between two colors in RGB space (0-441.67)."""
    a = _hex_to_rgb_tuple(hex_a)
    b = _hex_to_rgb_tuple(hex_b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


@mcp.tool
async def blend(hex_a: str, hex_b: str, ratio: float = 0.5) -> str:
    """Linear blend of two colors. `ratio=0` returns A, `ratio=1` returns B."""
    a = _hex_to_rgb_tuple(hex_a)
    b = _hex_to_rgb_tuple(hex_b)
    r = tuple(int(x + (y - x) * ratio) for x, y in zip(a, b))
    return _rgb_to_hex_str(*r)


@mcp.tool
async def is_dark(hex_str: str) -> bool:
    """Return True if `hex_str` is a 'dark' color by relative luminance (<0.5)."""
    return (await relative_luminance.__wrapped__(hex_str)) < 0.5


@mcp.tool
async def best_text_color(bg_hex: str) -> str:
    """Return '#000000' or '#FFFFFF' whichever has better contrast against `bg_hex`."""
    lum = await relative_luminance.__wrapped__(bg_hex)
    return "#000000" if lum > 0.5 else "#FFFFFF"


@mcp.tool
async def rgb_to_cmyk(r: int, g: int, b: int) -> List[float]:
    """Convert RGB (0-255) to [C, M, Y, K] in [0,1] using naive conversion."""
    if (r, g, b) == (0, 0, 0):
        return [0.0, 0.0, 0.0, 1.0]
    rn, gn, bn = r / 255, g / 255, b / 255
    k = 1 - max(rn, gn, bn)
    c = (1 - rn - k) / (1 - k) if k < 1 else 0
    m = (1 - gn - k) / (1 - k) if k < 1 else 0
    y = (1 - bn - k) / (1 - k) if k < 1 else 0
    return [c, m, y, k]
