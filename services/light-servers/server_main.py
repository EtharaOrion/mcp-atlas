import sys
import importlib
from pathlib import Path

sys.path.insert(0, "/app")

from fastmcp import FastMCP
from filesystem_server import mcp as filesystem_mcp

main = FastMCP("light-servers")
# fastmcp 3 takes the server first and the namespace second. The 2.x order
# was mount(prefix, server). Passing the 2.x order to 3.x does not raise at
# call time: it binds a str where the server is expected and only fails when
# the lifespan starts, as 'str' object has no attribute '_lifespan'.
main.mount(filesystem_mcp, "filesystem")

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
