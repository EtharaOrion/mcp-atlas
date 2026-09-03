"""Attach tool-call logging to every light-server process.

WHY THIS FILE EXISTS AT ALL. entrypoint.sh starts 161 INDEPENDENT
`fastmcp run <app>.py` processes. None of them imports server_main.py, so
middleware registered there is dead code during an actual task run -- it only
takes effect if someone runs the aggregated single-process server by hand.
Covering the real path means reaching inside 161 processes that share no
Python entry point.

Python imports `sitecustomize` automatically at interpreter startup for any
module found on sys.path, and the image already sets PYTHONPATH=/app. So this
one file runs in every server process without entrypoint.sh, the Dockerfile
CMD, or any app.py mentioning it.

WHAT IT DOES. Wraps FastMCP.__init__ so that every instance gets a
LoggingMiddleware the moment it is constructed -- which is before any app.py
has finished defining its tools, and long before the server starts serving.

Failure is silent BY DESIGN. This is diagnostics attached to a benchmark
fixture: if the middleware API moves in a future fastmcp, 161 servers must
still start and serve. A broken logger that takes the fleet down with it would
convert a missing log into a failed evaluation. The one-line notice on stderr
is the only signal, and `grep sitecustomize` over container logs is how you
tell "disabled" from "broken".

Env:
    LIGHT_SERVERS_TOOL_LOG    file to write tool-call lines to
                              (default /var/log/light-servers/tool_calls.log)
    LIGHT_SERVERS_LOG_PAYLOADS  "0" to log call metadata without arguments
    LIGHT_SERVERS_LOG_DISABLE   "1" to turn this off entirely
"""
import os
import sys

_LOG_PATH = os.environ.get("LIGHT_SERVERS_TOOL_LOG",
                           "/var/log/light-servers/tool_calls.log")
_PAYLOADS = os.environ.get("LIGHT_SERVERS_LOG_PAYLOADS", "1") != "0"


def _install() -> None:
    if os.environ.get("LIGHT_SERVERS_LOG_DISABLE") == "1":
        return

    import logging

    import fastmcp
    from fastmcp.server.middleware.logging import LoggingMiddleware

    # Every server process appends to ONE file on a shared volume. Each line is
    # stamped with the port so the interleaving is untangleable afterwards --
    # without it, 161 writers produce a log in which no line says who wrote it.
    port = "?"
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = sys.argv[i + 1]
            break

    handler = logging.FileHandler(_LOG_PATH, mode="a")
    handler.setFormatter(logging.Formatter(
        f"%(asctime)s :{port} %(levelname)s %(message)s"))

    logger = logging.getLogger(f"light-servers.tools.{port}")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    # Do not also hand these to the root logger: fastmcp installs a rich
    # handler on it, which would duplicate every line into stdout with ANSI
    # box-drawing wrapped at terminal width.
    logger.propagate = False

    _orig_init = fastmcp.FastMCP.__init__

    def _init(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        try:
            self.add_middleware(LoggingMiddleware(
                logger=logger,
                include_payloads=_PAYLOADS,
                max_payload_length=500,
            ))
        except Exception:
            # A server that cannot be instrumented must still serve.
            pass

    fastmcp.FastMCP.__init__ = _init


try:
    _install()
except Exception as exc:      # noqa: BLE001 - see module docstring
    print(f"[sitecustomize] tool-call logging not installed: "
          f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
