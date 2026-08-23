from fastmcp import FastMCP
import difflib
import json as _json
from typing import Dict, List, Optional
import Levenshtein

mcp = FastMCP("DiffServer")


def _lines(text: str) -> List[str]:
    return text.splitlines(keepends=True)


@mcp.tool
async def unified_diff(a: str, b: str, name_a: str = "a", name_b: str = "b", n_context: int = 3) -> str:
    """Return a unified-diff string comparing `a` to `b`."""
    return "".join(difflib.unified_diff(_lines(a), _lines(b), fromfile=name_a, tofile=name_b, n=n_context))


@mcp.tool
async def context_diff(a: str, b: str, name_a: str = "a", name_b: str = "b", n_context: int = 3) -> str:
    """Return a context-diff string comparing `a` to `b`."""
    return "".join(difflib.context_diff(_lines(a), _lines(b), fromfile=name_a, tofile=name_b, n=n_context))


@mcp.tool
async def html_diff(a: str, b: str, name_a: str = "a", name_b: str = "b") -> str:
    """Return an HTML side-by-side diff table of `a` vs `b`."""
    return difflib.HtmlDiff().make_file(_lines(a), _lines(b), fromdesc=name_a, todesc=name_b)


@mcp.tool
async def ndiff(a: str, b: str) -> str:
    """Return a human-readable ndiff of `a` vs `b`."""
    return "".join(difflib.ndiff(_lines(a), _lines(b)))


@mcp.tool
async def similarity_ratio(a: str, b: str) -> float:
    """Return a float in [0,1] measuring text similarity (difflib SequenceMatcher)."""
    return difflib.SequenceMatcher(None, a, b).ratio()


@mcp.tool
async def get_close_matches(word: str, possibilities: List[str], n: int = 3, cutoff: float = 0.6) -> List[str]:
    """Return up to `n` best matches for `word` in `possibilities`, above `cutoff` similarity."""
    return difflib.get_close_matches(word, possibilities, n=n, cutoff=cutoff)


@mcp.tool
async def word_diff(a: str, b: str) -> List[Dict]:
    """Return per-word diff as a list of {op: equal|insert|delete|replace, a, b} chunks."""
    aw = a.split()
    bw = b.split()
    matcher = difflib.SequenceMatcher(None, aw, bw)
    out: List[Dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        out.append({"op": tag, "a": " ".join(aw[i1:i2]), "b": " ".join(bw[j1:j2])})
    return out


@mcp.tool
async def line_diff(a: str, b: str) -> List[Dict]:
    """Return per-line diff opcodes between `a` and `b`."""
    al = a.splitlines()
    bl = b.splitlines()
    matcher = difflib.SequenceMatcher(None, al, bl)
    return [{"op": tag, "a": al[i1:i2], "b": bl[j1:j2]} for tag, i1, i2, j1, j2 in matcher.get_opcodes()]


@mcp.tool
async def longest_common_substring(a: str, b: str) -> str:
    """Return the longest contiguous substring shared by `a` and `b`."""
    matcher = difflib.SequenceMatcher(None, a, b)
    match = matcher.find_longest_match(0, len(a), 0, len(b))
    return a[match.a:match.a + match.size]


@mcp.tool
async def longest_common_subsequence(a: str, b: str) -> str:
    """Return the longest common subsequence (not necessarily contiguous) of `a` and `b`."""
    m, n = len(a), len(b)
    dp = [[""] * (n + 1) for _ in range(m + 1)]
    for i in range(m):
        for j in range(n):
            if a[i] == b[j]:
                dp[i + 1][j + 1] = dp[i][j] + a[i]
            else:
                dp[i + 1][j + 1] = max(dp[i + 1][j], dp[i][j + 1], key=len)
    return dp[m][n]


@mcp.tool
async def edit_distance(a: str, b: str) -> int:
    """Return the Levenshtein edit distance between `a` and `b`."""
    return Levenshtein.distance(a, b)


@mcp.tool
async def patch_apply(base: str, patch: str) -> str:
    """Apply a unified-diff patch to `base`. Naive: expects clean context, no fuzz."""
    base_lines = base.splitlines(keepends=True)
    patch_lines = patch.splitlines()
    out: List[str] = []
    i = 0
    idx = 0
    while idx < len(patch_lines):
        line = patch_lines[idx]
        if line.startswith("@@"):
            parts = line.split()
            hunk_a = parts[1]
            start_a = int(hunk_a.split(",")[0].lstrip("-").split(":")[0]) - 1
            while i < start_a:
                out.append(base_lines[i])
                i += 1
            idx += 1
            while idx < len(patch_lines) and not patch_lines[idx].startswith("@@"):
                pl = patch_lines[idx]
                if pl.startswith(" "):
                    out.append(base_lines[i])
                    i += 1
                elif pl.startswith("-"):
                    i += 1
                elif pl.startswith("+"):
                    out.append(pl[1:] + "\n")
                idx += 1
        else:
            idx += 1
    while i < len(base_lines):
        out.append(base_lines[i])
        i += 1
    return "".join(out)


@mcp.tool
async def three_way_merge(base: str, a: str, b: str) -> Dict:
    """Attempt a 3-way line merge of `a` and `b` against a common `base`. Returns {merged, conflict}."""
    base_l = base.splitlines()
    a_l = a.splitlines()
    b_l = b.splitlines()
    ma = difflib.SequenceMatcher(None, base_l, a_l)
    mb = difflib.SequenceMatcher(None, base_l, b_l)
    a_ops = {(i1, i2): (tag, j1, j2) for tag, i1, i2, j1, j2 in ma.get_opcodes() if tag != "equal"}
    b_ops = {(i1, i2): (tag, j1, j2) for tag, i1, i2, j1, j2 in mb.get_opcodes() if tag != "equal"}
    conflict = bool(set(a_ops.keys()) & set(b_ops.keys()))
    if conflict:
        merged = "<<<<<<< A\n" + a + "\n=======\n" + b + "\n>>>>>>> B"
    else:
        merged_lines: List[str] = []
        i = 0
        for tag, i1, i2, j1, j2 in ma.get_opcodes():
            if tag == "equal":
                merged_lines.extend(base_l[i1:i2])
            else:
                merged_lines.extend(a_l[j1:j2])
            i = i2
        merged = "\n".join(merged_lines)
    return {"merged": merged, "conflict": conflict}


@mcp.tool
async def deep_equal(a: str, b: str) -> bool:
    """Return True if two JSON-structured strings are structurally equal."""
    try:
        return _json.loads(a) == _json.loads(b)
    except _json.JSONDecodeError:
        return a == b


@mcp.tool
async def lines_added_removed(a: str, b: str) -> Dict[str, List[str]]:
    """Return dict {added: [...], removed: [...]} of line-level differences."""
    al = a.splitlines()
    bl = b.splitlines()
    matcher = difflib.SequenceMatcher(None, al, bl)
    added: List[str] = []
    removed: List[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("delete", "replace"):
            removed.extend(al[i1:i2])
        if tag in ("insert", "replace"):
            added.extend(bl[j1:j2])
    return {"added": added, "removed": removed}


@mcp.tool
async def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace and strip trailing whitespace from each line."""
    return "\n".join(" ".join(line.split()) for line in text.splitlines())


@mcp.tool
async def has_conflict_markers(text: str) -> bool:
    """Return True if `text` contains git-style conflict markers (<<<<<<<, =======, >>>>>>>)."""
    return "<<<<<<<" in text and "=======" in text and ">>>>>>>" in text


@mcp.tool
async def jaro_winkler(a: str, b: str) -> float:
    """Return the Jaro-Winkler similarity score between `a` and `b`."""
    return Levenshtein.jaro_winkler(a, b)


@mcp.tool
async def ratio_lev(a: str, b: str) -> float:
    """Return a Levenshtein-based similarity ratio in [0,1] between `a` and `b`."""
    return Levenshtein.ratio(a, b)
