# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=2,<3",
# ]
# ///
"""stdio MCP server that fronts the mcp-atlas sandbox's REST API.

Why this exists
---------------
The ``ghcr.io/scaleapi/mcp-atlas`` image does NOT speak the MCP protocol. It
serves a bespoke REST API on :1984 (``/health``, ``/list-tools``,
``/call-tool``, ``/enabled-servers`` -- see
services/agent-environment/src/agent_environment/main.py). Harbor's agents,
however, only know how to consume MCP servers.

Earlier bundles declared ``[[environment.mcp_servers]]`` pointing at
``http://localhost:18765/mcp``, a streamable-http endpoint the image never
exposed, so every ``harbor run`` died at the environment healthcheck before
the agent started. This module closes that gap: it runs inside the agent's
own container as a ``transport = "stdio"`` MCP server and proxies every
MCP call to the sandbox sidecar's REST API.

Configuration (environment variables)
-------------------------------------
MCP_SERVER_URL      Base URL of the sandbox sidecar. Default
                    ``http://mcp-server:1984``.
ENABLED_TOOLS_FILE  Optional path to a newline-delimited tool allowlist. When
                    present, ``tools/list`` is filtered to those names and any
                    call to a tool outside the list is refused. Default
                    ``/enabled_tools.txt``.
MCP_BRIDGE_TIMEOUT  Per-request timeout in seconds. Default 300.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://mcp-server:1984").rstrip("/")
ENABLED_TOOLS_FILE = os.environ.get("ENABLED_TOOLS_FILE", "/enabled_tools.txt")
REQUEST_TIMEOUT = float(os.environ.get("MCP_BRIDGE_TIMEOUT", "300"))


def _log(message: str) -> None:
    # stdout is the MCP transport -- diagnostics must go to stderr only.
    print(f"[mcp-rest-bridge] {message}", file=sys.stderr, flush=True)


def load_allowlist() -> set[str] | None:
    """Return the enabled-tool allowlist, or None when no allowlist applies.

    None and an empty set mean different things: None is "no allowlist file,
    expose everything the sandbox has", while an empty set would mean "expose
    nothing". An allowlist file that exists but is blank is treated as absent,
    since a bundle that accidentally ships an empty file should not silently
    disarm the whole task.
    """
    path = Path(ENABLED_TOOLS_FILE)
    if not path.is_file():
        return None
    names = {line.strip() for line in path.read_text().splitlines() if line.strip()}
    return names or None


def _post(path: str, payload: dict | None = None):
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        f"{SERVER_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if req.type not in ("http", "https"):
        raise ValueError(f"refusing non-HTTP(S) URL scheme: {req.full_url!r}")
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def _post_async(path: str, payload: dict | None = None):
    return await asyncio.to_thread(_post, path, payload)


def _to_content_blocks(raw) -> list[types.ContentBlock]:
    """Normalize the REST API's content blocks into MCP content blocks.

    /call-tool returns a JSON list of MCP ContentBlock dicts. Anything that
    isn't a recognized text block is passed through as its JSON encoding
    rather than dropped, so a tool returning images or embedded resources
    still reaches the agent as inspectable content instead of vanishing.
    """
    if raw is None:
        return [types.TextContent(type="text", text="")]
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return [types.TextContent(type="text", text=str(raw))]

    blocks: list[types.ContentBlock] = []
    for item in raw:
        if isinstance(item, dict) and item.get("type") == "text":
            blocks.append(types.TextContent(type="text", text=str(item.get("text", ""))))
        else:
            blocks.append(types.TextContent(type="text", text=json.dumps(item)))
    return blocks or [types.TextContent(type="text", text="")]


async def on_list_tools(ctx, params) -> types.ListToolsResult:
    allowlist = load_allowlist()
    raw = await _post_async("/list-tools")

    tools: list[types.Tool] = []
    for item in raw or []:
        name = item.get("name")
        if not name:
            continue
        if allowlist is not None and name not in allowlist:
            continue
        tools.append(
            types.Tool(
                name=name,
                description=item.get("description") or "",
                inputSchema=item.get("inputSchema") or {"type": "object", "properties": {}},
            )
        )

    if allowlist is not None:
        _log(f"exposing {len(tools)}/{len(raw or [])} tools (allowlist: {len(allowlist)} entries)")
    else:
        _log(f"exposing {len(tools)} tools (no allowlist)")
    return types.ListToolsResult(tools=tools)


def _error(message: str) -> types.CallToolResult:
    _log(message)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)], isError=True
    )


async def on_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    name = params.name
    allowlist = load_allowlist()
    if allowlist is not None and name not in allowlist:
        # Refuse rather than proxy: the allowlist is the task's tool-scoping
        # contract, and a silent proxy would let a task be solved with tools
        # it was never granted.
        return _error(f"Tool {name!r} is not enabled for this task")

    try:
        raw = await _post_async(
            "/call-tool",
            {"tool_name": name, "tool_args": params.arguments or {}},
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        return _error(f"sandbox returned HTTP {exc.code} for {name!r}: {detail}")
    except urllib.error.URLError as exc:
        return _error(f"sandbox unreachable at {SERVER_URL} for {name!r}: {exc.reason}")

    return types.CallToolResult(content=_to_content_blocks(raw))


server = Server(
    "mcp-atlas",
    version="1.0.0",
    on_list_tools=on_list_tools,
    on_call_tool=on_call_tool,
)


async def main() -> None:
    _log(f"starting; sandbox={SERVER_URL} allowlist_file={ENABLED_TOOLS_FILE}")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
