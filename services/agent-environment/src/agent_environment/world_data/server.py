"""Local MCP server that serves offline "world data" JSON fixtures.

Instead of calling external APIs (Airbnb, CRM, Calendar, ...), agents can query
snapshots stored as one JSON file per service (e.g. ``LightAirbnb.json``).

The data files are bundled with the package in the ``data/`` subfolder; set the
``WORLD_DATA_DIR`` environment variable to serve a different directory instead.
"""

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastmcp import FastMCP

DEFAULT_DATA_DIR = Path(__file__).parent / "data"
FILE_PREFIX = "Light"

mcp = FastMCP("world-data")


def _data_dir() -> Path:
    override = os.getenv("WORLD_DATA_DIR", "").strip()
    return Path(override).expanduser() if override else DEFAULT_DATA_DIR


def _service_files() -> dict[str, Path]:
    """Map normalized service name (lowercase, no ``Light`` prefix) to its file."""
    data_dir = _data_dir()
    if not data_dir.is_dir():
        raise FileNotFoundError(
            f"World data directory not found: {data_dir}. "
            "Set WORLD_DATA_DIR to the folder containing the Light*.json files."
        )
    files: dict[str, Path] = {}
    for path in sorted(data_dir.glob("*.json")):
        stem = path.stem
        name = stem[len(FILE_PREFIX) :] if stem.startswith(FILE_PREFIX) else stem
        files[name.lower()] = path
    return files


def _load_service(service: str) -> dict[str, Any]:
    files = _service_files()
    key = service.lower().removeprefix(FILE_PREFIX.lower())
    if key not in files:
        available = ", ".join(sorted(files))
        raise ValueError(f"Unknown service '{service}'. Available: {available}")
    with open(files[key]) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        data = {"records": data}
    return data


def _iter_records(collection: Any) -> list[Any]:
    """Collections are either a list of records or a dict keyed by record id."""
    if isinstance(collection, dict):
        return list(collection.values())
    if isinstance(collection, list):
        return collection
    return [collection]


@mcp.tool
def list_services() -> list[str]:
    """List all services that have offline world data available."""
    return sorted(_service_files())


@mcp.tool
def describe_service(service: str) -> dict[str, Any]:
    """Show a service's collections, record counts, and sample record fields."""
    data = _load_service(service)
    description: dict[str, Any] = {}
    for collection_name, collection in data.items():
        records = _iter_records(collection)
        sample_fields: list[str] = []
        for record in records:
            if isinstance(record, dict):
                sample_fields = sorted(record.keys())
                break
        description[collection_name] = {
            "record_count": len(records),
            "sample_fields": sample_fields,
        }
    return description


@mcp.tool
def get_service_data(service: str, collection: Optional[str] = None) -> Any:
    """Return a service's data — the whole snapshot, or one collection if given."""
    data = _load_service(service)
    if collection is None:
        return data
    if collection not in data:
        available = ", ".join(sorted(data))
        raise ValueError(
            f"Service '{service}' has no collection '{collection}'. "
            f"Available: {available}"
        )
    return data[collection]


@mcp.tool
def search_records(
    service: str,
    collection: str,
    field: str,
    value: str,
) -> list[Any]:
    """Find records in a collection where a field equals or contains the value.

    Matching is case-insensitive: exact match for non-string fields, substring
    match for strings. Nested fields can be addressed with dots (a.b.c).
    """
    records = _iter_records(get_service_data.fn(service, collection))
    needle = value.lower()
    matches = []
    for record in records:
        current: Any = record
        for part in field.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                current = None
                break
        if current is None:
            continue
        if isinstance(current, str):
            if needle in current.lower():
                matches.append(record)
        elif str(current).lower() == needle:
            matches.append(record)
    return matches


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
