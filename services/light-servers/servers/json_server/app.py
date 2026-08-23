from fastmcp import FastMCP
import json as _json
import yaml
from typing import Any, Dict, List, Optional
from jsonschema import Draft7Validator

mcp = FastMCP("JSONServer")


def _split_path(path: str) -> List[str]:
    if not path or path == "$":
        return []
    p = path.lstrip("$").lstrip(".")
    out: List[str] = []
    cur = ""
    i = 0
    while i < len(p):
        ch = p[i]
        if ch == ".":
            if cur:
                out.append(cur)
                cur = ""
        elif ch == "[":
            if cur:
                out.append(cur)
                cur = ""
            j = p.index("]", i)
            idx = p[i + 1:j].strip('"').strip("'")
            out.append(idx)
            i = j
        else:
            cur += ch
        i += 1
    if cur:
        out.append(cur)
    return out


def _get_by_parts(obj: Any, parts: List[str]) -> Any:
    for p in parts:
        if isinstance(obj, list):
            obj = obj[int(p)]
        elif isinstance(obj, dict):
            obj = obj[p]
        else:
            raise KeyError(p)
    return obj


def _set_by_parts(obj: Any, parts: List[str], value: Any) -> Any:
    if not parts:
        return value
    parent = _get_by_parts(obj, parts[:-1])
    last = parts[-1]
    if isinstance(parent, list):
        parent[int(last)] = value
    else:
        parent[last] = value
    return obj


def _delete_by_parts(obj: Any, parts: List[str]) -> Any:
    if not parts:
        return None
    parent = _get_by_parts(obj, parts[:-1])
    last = parts[-1]
    if isinstance(parent, list):
        del parent[int(last)]
    else:
        del parent[last]
    return obj


@mcp.tool
async def parse(text: str) -> Any:
    """Parse a JSON string into its Python representation."""
    return _json.loads(text)


@mcp.tool
async def stringify(value: Any, indent: Optional[int] = None) -> str:
    """Serialize a Python value as JSON. `indent` controls pretty-print width."""
    return _json.dumps(value, indent=indent, ensure_ascii=False)


@mcp.tool
async def pretty(text: str, indent: int = 2) -> str:
    """Pretty-print an existing JSON string with the given indent."""
    return _json.dumps(_json.loads(text), indent=indent, ensure_ascii=False)


@mcp.tool
async def minify(text: str) -> str:
    """Return the compact form of a JSON string (no whitespace)."""
    return _json.dumps(_json.loads(text), separators=(",", ":"), ensure_ascii=False)


@mcp.tool
async def validate(text: str, schema: Dict) -> Dict:
    """Validate JSON `text` against a JSON Schema. Returns {valid, errors}."""
    try:
        data = _json.loads(text)
    except _json.JSONDecodeError as e:
        return {"valid": False, "errors": [f"invalid json: {e}"]}
    v = Draft7Validator(schema)
    errs = [f"{list(e.absolute_path)}: {e.message}" for e in v.iter_errors(data)]
    return {"valid": len(errs) == 0, "errors": errs}


@mcp.tool
async def get_path(text: str, path: str) -> Any:
    """Return the value at dot/bracket `path` in JSON `text`. Path starts with $ or a key."""
    return _get_by_parts(_json.loads(text), _split_path(path))


@mcp.tool
async def set_path(text: str, path: str, value: Any) -> str:
    """Return JSON with the value at `path` replaced by `value`."""
    obj = _json.loads(text)
    obj = _set_by_parts(obj, _split_path(path), value)
    return _json.dumps(obj)


@mcp.tool
async def delete_path(text: str, path: str) -> str:
    """Return JSON with the key/index at `path` removed."""
    obj = _json.loads(text)
    obj = _delete_by_parts(obj, _split_path(path))
    return _json.dumps(obj)


def _deep_merge(a: Any, b: Any) -> Any:
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = _deep_merge(a.get(k), v) if k in a else v
        return out
    return b


@mcp.tool
async def merge(a: str, b: str) -> str:
    """Deep-merge two JSON documents; keys in `b` override `a`."""
    return _json.dumps(_deep_merge(_json.loads(a), _json.loads(b)))


def _diff_recurse(a: Any, b: Any, path: str = "$") -> List[Dict]:
    diffs: List[Dict] = []
    if type(a) != type(b):
        diffs.append({"path": path, "op": "type_change", "from": a, "to": b})
        return diffs
    if isinstance(a, dict):
        for k in a.keys() | b.keys():
            if k not in a:
                diffs.append({"path": f"{path}.{k}", "op": "add", "value": b[k]})
            elif k not in b:
                diffs.append({"path": f"{path}.{k}", "op": "remove", "value": a[k]})
            else:
                diffs.extend(_diff_recurse(a[k], b[k], f"{path}.{k}"))
    elif isinstance(a, list):
        for i in range(max(len(a), len(b))):
            if i >= len(a):
                diffs.append({"path": f"{path}[{i}]", "op": "add", "value": b[i]})
            elif i >= len(b):
                diffs.append({"path": f"{path}[{i}]", "op": "remove", "value": a[i]})
            else:
                diffs.extend(_diff_recurse(a[i], b[i], f"{path}[{i}]"))
    else:
        if a != b:
            diffs.append({"path": path, "op": "change", "from": a, "to": b})
    return diffs


@mcp.tool
async def diff(a: str, b: str) -> List[Dict]:
    """Return a structural diff between two JSON documents."""
    return _diff_recurse(_json.loads(a), _json.loads(b))


@mcp.tool
async def keys(text: str) -> List[str]:
    """Return the top-level keys of a JSON object."""
    obj = _json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("top-level value must be an object")
    return list(obj.keys())


def _flatten(obj: Any, prefix: str, sep: str, out: Dict[str, Any]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(v, f"{prefix}{sep}{k}" if prefix else k, sep, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _flatten(v, f"{prefix}{sep}{i}" if prefix else str(i), sep, out)
    else:
        out[prefix] = obj


@mcp.tool
async def flatten(text: str, sep: str = ".") -> Dict[str, Any]:
    """Return a flat dict mapping dotted paths to leaf values."""
    out: Dict[str, Any] = {}
    _flatten(_json.loads(text), "", sep, out)
    return out


@mcp.tool
async def unflatten(flat: Dict[str, Any], sep: str = ".") -> Any:
    """Rebuild a nested structure from a flat dict of dotted paths."""
    root: Any = {}
    for key, value in flat.items():
        parts = key.split(sep)
        cur = root
        for i, p in enumerate(parts):
            last = i == len(parts) - 1
            if last:
                cur[p] = value
            else:
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
    return root


@mcp.tool
async def to_yaml(text: str) -> str:
    """Convert a JSON string to YAML."""
    return yaml.safe_dump(_json.loads(text), sort_keys=False, allow_unicode=True)


@mcp.tool
async def from_yaml(text: str) -> str:
    """Convert a YAML string to JSON."""
    return _json.dumps(yaml.safe_load(text))


def _find_paths(obj: Any, target_key: str, path: str, out: List[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}"
            if k == target_key:
                out.append(new_path)
            _find_paths(v, target_key, new_path, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _find_paths(v, target_key, f"{path}[{i}]", out)


@mcp.tool
async def find_paths(text: str, key: str) -> List[str]:
    """Return all dotted paths where `key` occurs anywhere in the JSON tree."""
    out: List[str] = []
    _find_paths(_json.loads(text), key, "$", out)
    return out


@mcp.tool
async def size(text: str) -> int:
    """Return the length of the top-level container (object keys or array items)."""
    obj = _json.loads(text)
    if isinstance(obj, (dict, list, str)):
        return len(obj)
    raise ValueError("top-level value has no length")


@mcp.tool
async def is_valid(text: str) -> bool:
    """Return True if `text` parses as valid JSON, else False."""
    try:
        _json.loads(text)
        return True
    except _json.JSONDecodeError:
        return False


@mcp.tool
async def sort_keys(text: str, indent: Optional[int] = None) -> str:
    """Return the JSON with all object keys sorted recursively (alphabetical)."""
    return _json.dumps(_json.loads(text), sort_keys=True, indent=indent, ensure_ascii=False)
