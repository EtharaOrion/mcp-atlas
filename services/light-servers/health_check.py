#!/usr/bin/env python3
"""Probe every light-server in the fleet and report readiness, one line each.

entrypoint.sh launches its servers as background processes and then `wait`s.
Until now it printed "Servers started." and nothing verified that any of them
ever bound its port -- a server that died on import looked exactly like one
serving happily, and the first evidence of the difference was an agent's tool
call failing mid-trajectory.

This runs in the foreground after the launch loop, polls each port until it
accepts a connection, prints one line per server, and exits.

EVERY SERVER IN THE TABLE IS LISTED, not just the ones this task enabled. A
task bundle typically starts a handful of the 161 and leaves the rest alone, so
most lines on a healthy run read DOWN. That is expected and is why the two
groups are reported separately: a DOWN server the task never asked for is
inventory, and a DOWN server the task DECLARED is a broken run. Only the
second kind sets the exit code -- otherwise every normal run would exit 1 and
the code would carry no information at all.

WHY THE PORT MAP IS PARSED, NOT COPIED. Every port lives in exactly one place:
the `SERVER_CMDS` table in entrypoint.sh. A second copy here would be correct
on the day it was written and would silently drift the first time a server
moved -- reporting UP on a port nothing serves, or omitting a server entirely.
So this parses the same table the launcher uses.

WHY THE TWO GROUPS GET DIFFERENT DEADLINES. Enabled servers are still booting
when this starts, so they are retried on a deadline that scales with how many
were launched -- a fixed 10s budget reports 0/161 DOWN on a fleet that is
merely slow, which is worse than no log because it is confidently wrong.
Servers that were never launched cannot come up no matter how long we wait, so
they get a single pass. Retrying them would add ~13 minutes to every run to
re-confirm a foregone conclusion.

WHAT A PASS ACTUALLY MEANS. A TCP connect proves a process is listening on the
port. It does not prove the server completes an MCP handshake or that its world
loaded. That is the honest limit of a socket probe, and it is still the
difference between "the process is up" and "the process died on import", which
is the failure this exists to catch.

WHY RESULTS ARE WRITTEN INCREMENTALLY. The probe file is written line-by-line
as each future completes (via as_completed) rather than batch-flushed at the
end. This ensures partial results survive a SIGTERM: when docker-compose tears
down the container after the agent run, whatever servers had already responded
are recorded. Servers still being retried at teardown time are simply absent
from the probe file; harbor_to_output.py treats those as UNKNOWN.

Env:
    ENABLED_SERVERS   comma-separated subset, the same variable entrypoint.sh
                      reads. Unset means every server was launched.
    HEALTH_DEADLINE   seconds to keep retrying enabled servers
                      (default: 30 + 5*n, max 900). Set 0 for a single pass.
    HEALTH_INTERVAL   seconds between attempts (default 2.0)
    HEALTH_TIMEOUT    per-connect timeout in seconds (default 1.0)
    HEALTH_ENTRYPOINT path to entrypoint.sh (default /app/entrypoint.sh)
    HEALTH_LOG        file to tee the report into
                      (default /var/log/light-servers/health.log)

Exit 0 if every ENABLED server is UP, 1 if any enabled server is DOWN.
"""
from __future__ import annotations

import os
import re
import signal
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ENTRYPOINT = os.environ.get("HEALTH_ENTRYPOINT", "/app/entrypoint.sh")
INTERVAL = float(os.environ.get("HEALTH_INTERVAL", "2.0"))
TIMEOUT = float(os.environ.get("HEALTH_TIMEOUT", "1.0"))
HOST = os.environ.get("HEALTH_HOST", "127.0.0.1")
LOG_PATH = os.environ.get("HEALTH_LOG", "/var/log/light-servers/health.log")

DEADLINE_BASE = 30.0
DEADLINE_PER_SERVER = 5.0
DEADLINE_CAP = 900.0

# SERVER_CMDS["name"]="... --port 9000"
_CMD_RE = re.compile(r'^SERVER_CMDS\["([^"]+)"\]="(.*)"\s*$')
_PORT_RE = re.compile(r"--port\s+(\d+)")

_log_fh = None
_log_lock = threading.Lock()


def _open_log() -> None:
    global _log_fh
    try:
        os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
        _log_fh = open(LOG_PATH, "w")
    except OSError as exc:
        print(f"[HEALTH] could not open {LOG_PATH}: {exc}", file=sys.stderr, flush=True)


def _close_log() -> None:
    if _log_fh is not None:
        try:
            _log_fh.close()
        except OSError:
            pass


def _on_sigterm(sig, frame) -> None:
    _close_log()
    sys.exit(0)


def log(msg: str) -> None:
    """One line to stdout (docker logs) and immediately to the log file."""
    print(msg, flush=True)
    if _log_fh is not None:
        with _log_lock:
            _log_fh.write(msg + "\n")
            _log_fh.flush()


def parse_server_ports(path: str) -> dict[str, int]:
    """name -> port, read from entrypoint.sh's SERVER_CMDS table."""
    ports: dict[str, int] = {}
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except OSError as exc:
        log(f"[HEALTH] cannot read {path}: {exc}")
        return ports

    for line in lines:
        m = _CMD_RE.match(line.strip())
        if not m:
            continue
        name, cmd = m.group(1), m.group(2)
        p = _PORT_RE.search(cmd)
        if p:
            ports[name] = int(p.group(1))
        else:
            # A server with no --port cannot be probed. Say so rather than
            # dropping it, or the total silently shrinks and 160/160 reads
            # as a clean run.
            log(f"[HEALTH] WARN  {name}: no --port in its command; not probed")
    return ports


def enabled_names(ports: dict[str, int]) -> set[str]:
    """Which servers entrypoint.sh actually launched.

    The launcher strips ALL spaces from each name (`${name// /}`), not just the
    ends, and skips unknown names with a warning. Both behaviours are copied
    here so the ENABLED column matches what was really started -- a probe that
    disagreed with the launcher would blame the fleet for a typo in compose.
    """
    raw = os.environ.get("ENABLED_SERVERS", "").strip()
    if not raw:
        return set(ports)

    names: set[str] = set()
    for part in raw.split(","):
        name = part.replace(" ", "")
        if not name:
            continue
        if name in ports:
            names.add(name)
        else:
            log(f"[HEALTH] WARN  unknown server '{name}' in ENABLED_SERVERS; "
                f"nothing was started for it")
    return names


def resolve_deadline(n: int) -> float:
    raw = os.environ.get("HEALTH_DEADLINE")
    if raw is not None:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return min(DEADLINE_CAP, DEADLINE_BASE + DEADLINE_PER_SERVER * n)


def make_probe(give_up_at: float):
    def probe(port: int) -> bool:
        """True as soon as something accepts a connection on the port."""
        while True:
            try:
                with socket.create_connection((HOST, port), timeout=TIMEOUT):
                    return True
            except OSError:
                if time.monotonic() >= give_up_at:
                    return False
                time.sleep(INTERVAL)
    return probe


def main() -> int:
    _open_log()
    signal.signal(signal.SIGTERM, _on_sigterm)

    ports = parse_server_ports(ENTRYPOINT)
    if not ports:
        log("[HEALTH] no servers found to probe")
        _close_log()
        return 1

    enabled = enabled_names(ports)
    launched = {n: p for n, p in ports.items() if n in enabled}
    idle = {n: p for n, p in ports.items() if n not in enabled}

    deadline = resolve_deadline(len(launched))
    log(f"[HEALTH] probing all {len(ports)} servers "
        f"({len(launched)} enabled, up to {deadline:g}s; "
        f"{len(idle)} not enabled, single pass)")

    started = time.monotonic()
    now = time.monotonic()

    results: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(ports))) as pool:
        fut_to_name: dict = {}
        for name, port in launched.items():
            fut_to_name[pool.submit(make_probe(now + deadline), port)] = name
        for name, port in idle.items():
            fut_to_name[pool.submit(make_probe(now), port)] = name

        # Write each result immediately as its future completes so the probe
        # file survives a SIGTERM mid-run (results are in completion order,
        # not port order -- harbor_to_output.py parses with regex, order is
        # irrelevant).
        for fut in as_completed(fut_to_name):
            name = fut_to_name[fut]
            ok = fut.result()
            results[name] = ok
            port = ports[name]
            tag = "" if name in enabled else "  (not enabled)"
            log(f"[HEALTH] {'UP  ' if ok else 'DOWN'}  {name:<24} :{port}{tag}")

    down_enabled, up_idle = [], []
    for name, port in sorted(ports.items(), key=lambda kv: kv[1]):
        if name in enabled and not results[name]:
            down_enabled.append(f"{name}:{port}")
        elif name not in enabled and results.get(name):
            up_idle.append(f"{name}:{port}")

    up_total = sum(1 for v in results.values() if v)
    up_hot = len(launched) - len(down_enabled)
    elapsed = time.monotonic() - started

    log(f"[HEALTH] enabled: {up_hot}/{len(launched)} healthy")
    log(f"[HEALTH] fleet:   {up_total}/{len(ports)} up, "
        f"{len(idle)} not enabled for this task  ({elapsed:.1f}s)")
    if down_enabled:
        log(f"[HEALTH] DOWN (enabled, THIS IS A FAULT): {', '.join(down_enabled)}")
    if up_idle:
        # Something is serving a port the launcher was not asked to start. Worth
        # a line: a stale container on the same network can shadow a port and
        # answer tool calls the task never intended to expose.
        log(f"[HEALTH] UP but not enabled (unexpected): {', '.join(up_idle)}")

    _close_log()
    return 1 if down_enabled else 0


if __name__ == "__main__":
    raise SystemExit(main())
