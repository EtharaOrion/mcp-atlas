import sys
import importlib
from pathlib import Path

sys.path.insert(0, "/app")

from fastmcp import FastMCP
from fastmcp.server.middleware.logging import LoggingMiddleware
from filesystem_server import mcp as filesystem_mcp

main = FastMCP("light-servers")
# fastmcp 3 takes the server first and the namespace second. The 2.x order
# was mount(prefix, server). Passing the 2.x order to 3.x does not raise at
# call time: it binds a str where the server is expected and only fails when
# the lifespan starts, as 'str' object has no attribute '_lifespan'.
main.mount(filesystem_mcp, "filesystem")

# Log every MCP request through the aggregated server, arguments included, so a
# trajectory can be reconstructed from container logs alone. Registered before
# the mounts below only for readability -- middleware wraps the server, not the
# sub-servers, so it sees calls to all of them whenever they are mounted.
#
# Payloads are truncated at 500 chars: a light-server response can be an entire
# table, and an untruncated log would bury the call sequence in world state.
#
# This covers the server_main.py single-process path ONLY. entrypoint.sh runs a
# different topology -- 161 independent `fastmcp run app.py` processes that
# never import this file -- so it gets no tool-call logging from this line.
# Covering that path means touching each app.py individually.
main.add_middleware(LoggingMiddleware(include_payloads=True, max_payload_length=500))

_SERVERS_DIR = Path("/app/servers")
for _app_path in sorted(_SERVERS_DIR.glob("*/app.py")):
    _name = _app_path.parent.name
    try:
        _mod = importlib.import_module(f"servers.{_name}.app")
        _sub = getattr(_mod, "mcp", None)
        if _sub is not None:
            main.mount(_sub, _name)
    except Exception as _e:
        print(f"[light-servers] skip servers/{_name}: {_e}", flush=True)

_SOFTWARE_DIR = Path("/app/software")
for _app_path in sorted(_SOFTWARE_DIR.glob("Light*/app.py")):
    _name = _app_path.parent.name
    try:
        _mod = importlib.import_module(f"software.{_name}.app")
        _sub = getattr(_mod, "mcp", None)
        if _sub is not None:
            main.mount(_sub, _name.lower())
    except Exception as _e:
        print(f"[light-servers] skip software/{_name}: {_e}", flush=True)

if __name__ == "__main__":
    main.run(transport="streamable-http", port=9000, host="0.0.0.0")
