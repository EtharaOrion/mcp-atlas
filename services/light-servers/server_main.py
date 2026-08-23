import sys
import importlib
from pathlib import Path

sys.path.insert(0, "/app")

from fastmcp import FastMCP
from filesystem_server import mcp as filesystem_mcp

main = FastMCP("light-servers")
main.mount("filesystem", filesystem_mcp)

_SERVERS_DIR = Path("/app/servers")
for _app_path in sorted(_SERVERS_DIR.glob("*/app.py")):
    _name = _app_path.parent.name
    try:
        _mod = importlib.import_module(f"servers.{_name}.app")
        _sub = getattr(_mod, "mcp", None)
        if _sub is not None:
            main.mount(_name, _sub)
    except Exception as _e:
        print(f"[light-servers] skip servers/{_name}: {_e}", flush=True)

_SOFTWARE_DIR = Path("/app/software")
for _app_path in sorted(_SOFTWARE_DIR.glob("Light*/app.py")):
    _name = _app_path.parent.name
    try:
        _mod = importlib.import_module(f"software.{_name}.app")
        _sub = getattr(_mod, "mcp", None)
        if _sub is not None:
            main.mount(_name.lower(), _sub)
    except Exception as _e:
        print(f"[light-servers] skip software/{_name}: {_e}", flush=True)

if __name__ == "__main__":
    main.run(transport="streamable-http", port=9000, host="0.0.0.0")
