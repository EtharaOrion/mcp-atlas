from fastmcp import FastMCP
import csv
import io
from typing import Dict, List, Optional, Any

mcp = FastMCP("CSVServer")


def _reader(text: str, delimiter: str = ","):
    return csv.reader(io.StringIO(text), delimiter=delimiter)


def _dict_reader(text: str, delimiter: str = ","):
    return csv.DictReader(io.StringIO(text), delimiter=delimiter)


def _writer_str(rows: List[List[Any]], delimiter: str = ",") -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    w.writerows(rows)
    return buf.getvalue()


@mcp.tool
async def parse_csv(text: str, delimiter: str = ",") -> List[Dict[str, str]]:
    """Parse CSV `text` as a list of row dicts, using the first row as header."""
    return list(_dict_reader(text, delimiter))


@mcp.tool
async def parse_csv_rows(text: str, delimiter: str = ",") -> List[List[str]]:
    """Parse CSV `text` as a list of raw rows (no header interpretation)."""
    return [row for row in _reader(text, delimiter)]


@mcp.tool
async def to_csv(rows: List[Dict[str, Any]], headers: Optional[List[str]] = None, delimiter: str = ",") -> str:
    """Serialize a list of row dicts as a CSV string. If `headers` omitted, uses keys of first row."""
    if not rows:
        return ""
    fieldnames = headers or list(rows[0].keys())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, delimiter=delimiter, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in fieldnames})
    return buf.getvalue()


@mcp.tool
async def to_csv_from_rows(rows: List[List[Any]], delimiter: str = ",") -> str:
    """Serialize a list of raw rows as a CSV string."""
    return _writer_str(rows, delimiter)


@mcp.tool
async def filter_rows(text: str, column: str, value: str, delimiter: str = ",") -> str:
    """Return CSV containing only rows where `column` equals `value`."""
    rows = list(_dict_reader(text, delimiter))
    kept = [r for r in rows if r.get(column) == value]
    return await to_csv.__wrapped__(kept, list(rows[0].keys()) if rows else None, delimiter)


@mcp.tool
async def select_columns(text: str, columns: List[str], delimiter: str = ",") -> str:
    """Return CSV containing only the named `columns`, in the given order."""
    rows = list(_dict_reader(text, delimiter))
    projected = [{c: r.get(c, "") for c in columns} for r in rows]
    return await to_csv.__wrapped__(projected, columns, delimiter)


@mcp.tool
async def count_rows(text: str, delimiter: str = ",") -> int:
    """Return the number of data rows in CSV `text` (excluding header)."""
    return sum(1 for _ in _dict_reader(text, delimiter))


@mcp.tool
async def get_headers(text: str, delimiter: str = ",") -> List[str]:
    """Return the header row of CSV `text` as a list of column names."""
    first = next(_reader(text, delimiter), [])
    return first


@mcp.tool
async def get_column(text: str, column: str, delimiter: str = ",") -> List[str]:
    """Return all values of `column` as a list of strings."""
    return [r.get(column, "") for r in _dict_reader(text, delimiter)]


@mcp.tool
async def agg_sum(text: str, column: str, delimiter: str = ",") -> float:
    """Sum numeric values in `column`. Non-numeric cells are skipped."""
    total = 0.0
    for r in _dict_reader(text, delimiter):
        try:
            total += float(r.get(column, "") or 0)
        except ValueError:
            continue
    return total


@mcp.tool
async def agg_avg(text: str, column: str, delimiter: str = ",") -> float:
    """Average numeric values in `column`. Non-numeric cells are skipped."""
    vals: List[float] = []
    for r in _dict_reader(text, delimiter):
        try:
            vals.append(float(r.get(column, "") or 0))
        except ValueError:
            continue
    return sum(vals) / len(vals) if vals else 0.0


@mcp.tool
async def agg_min(text: str, column: str, delimiter: str = ",") -> Optional[float]:
    """Minimum numeric value in `column`, or None if no numeric cells."""
    vals: List[float] = []
    for r in _dict_reader(text, delimiter):
        try:
            vals.append(float(r.get(column, "") or 0))
        except ValueError:
            continue
    return min(vals) if vals else None


@mcp.tool
async def agg_max(text: str, column: str, delimiter: str = ",") -> Optional[float]:
    """Maximum numeric value in `column`, or None if no numeric cells."""
    vals: List[float] = []
    for r in _dict_reader(text, delimiter):
        try:
            vals.append(float(r.get(column, "") or 0))
        except ValueError:
            continue
    return max(vals) if vals else None


@mcp.tool
async def agg_count(text: str, column: str, delimiter: str = ",") -> int:
    """Count non-empty cells in `column`."""
    return sum(1 for r in _dict_reader(text, delimiter) if r.get(column, "") != "")


@mcp.tool
async def sort_rows(text: str, column: str, ascending: bool = True, delimiter: str = ",") -> str:
    """Return CSV sorted by `column` in the given order. Numeric sort attempted, falls back to string."""
    rows = list(_dict_reader(text, delimiter))
    def key(r: Dict[str, str]):
        v = r.get(column, "")
        try:
            return (0, float(v))
        except ValueError:
            return (1, v)
    rows.sort(key=key, reverse=not ascending)
    return await to_csv.__wrapped__(rows, list(rows[0].keys()) if rows else None, delimiter)


@mcp.tool
async def head(text: str, n: int = 5, delimiter: str = ",") -> str:
    """Return CSV with only the first `n` data rows (header preserved)."""
    rows = list(_dict_reader(text, delimiter))
    return await to_csv.__wrapped__(rows[:n], list(rows[0].keys()) if rows else None, delimiter)


@mcp.tool
async def tail(text: str, n: int = 5, delimiter: str = ",") -> str:
    """Return CSV with only the last `n` data rows (header preserved)."""
    rows = list(_dict_reader(text, delimiter))
    return await to_csv.__wrapped__(rows[-n:], list(rows[0].keys()) if rows else None, delimiter)


@mcp.tool
async def unique_values(text: str, column: str, delimiter: str = ",") -> List[str]:
    """Return the ordered set of unique values in `column`."""
    seen = []
    seen_set = set()
    for r in _dict_reader(text, delimiter):
        v = r.get(column, "")
        if v not in seen_set:
            seen_set.add(v)
            seen.append(v)
    return seen


@mcp.tool
async def group_by_count(text: str, column: str, delimiter: str = ",") -> Dict[str, int]:
    """Group by `column` and count rows per distinct value."""
    counts: Dict[str, int] = {}
    for r in _dict_reader(text, delimiter):
        v = r.get(column, "")
        counts[v] = counts.get(v, 0) + 1
    return counts


@mcp.tool
async def transpose(text: str, delimiter: str = ",") -> str:
    """Return CSV with rows and columns swapped."""
    rows = list(_reader(text, delimiter))
    if not rows:
        return ""
    cols = list(zip(*rows))
    return _writer_str([list(c) for c in cols], delimiter)


@mcp.tool
async def detect_delimiter(text: str, candidates: str = ",;\t|") -> str:
    """Try to auto-detect the delimiter used in CSV `text`. Falls back to comma."""
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=candidates)
        return dialect.delimiter
    except csv.Error:
        return ","


@mcp.tool
async def has_header(text: str) -> bool:
    """Heuristically detect whether the first row of `text` looks like a header."""
    try:
        return csv.Sniffer().has_header(text[:4096])
    except csv.Error:
        return False
