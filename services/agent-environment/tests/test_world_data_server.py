"""Tests for the local world-data MCP server."""

import asyncio
import json

import pytest
from fastmcp import Client

from agent_environment.world_data.server import mcp


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    (tmp_path / "LightAirbnb.json").write_text(
        json.dumps(
            {
                "reservations": [
                    {"id": "r1", "guest": {"name": "Ada"}, "nights": 3},
                    {"id": "r2", "guest": {"name": "Bob"}, "nights": 2},
                ]
            }
        )
    )
    (tmp_path / "LightCRM.json").write_text(
        json.dumps({"contacts": {"c1": {"name": "Ada Lovelace"}}})
    )
    monkeypatch.setenv("WORLD_DATA_DIR", str(tmp_path))
    return tmp_path


def _call(tool, args):
    async def _run():
        async with Client(mcp) as client:
            result = await client.call_tool(tool, args)
            return json.loads(result.content[0].text)

    return asyncio.run(_run())


def test_list_services(data_dir):
    assert _call("list_services", {}) == ["airbnb", "crm"]


def test_bundled_data_is_default(monkeypatch):
    monkeypatch.delenv("WORLD_DATA_DIR", raising=False)
    services = _call("list_services", {})
    assert len(services) >= 100
    assert "airbnb" in services and "crm" in services


def test_describe_service(data_dir):
    description = _call("describe_service", {"service": "airbnb"})
    assert description["reservations"]["record_count"] == 2
    assert description["reservations"]["sample_fields"] == ["guest", "id", "nights"]


def test_get_service_data_accepts_light_prefix(data_dir):
    data = _call("get_service_data", {"service": "LightCRM", "collection": "contacts"})
    assert data == {"c1": {"name": "Ada Lovelace"}}


def test_search_records_nested_field(data_dir):
    matches = _call(
        "search_records",
        {
            "service": "airbnb",
            "collection": "reservations",
            "field": "guest.name",
            "value": "ada",
        },
    )
    assert [m["id"] for m in matches] == ["r1"]


def test_unknown_service_lists_available(data_dir):
    with pytest.raises(Exception, match="Unknown service"):
        _call("get_service_data", {"service": "nope"})
