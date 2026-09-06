#!/usr/bin/env python3
"""Detect whether the agent reached the public internet, and block the run if it did.

    scripts/detect_internet_use.py <trajectory.json> [--json OUT] [--warn-only]

Exit 0 = clean. Exit 2 = the model used the internet; the run is blocked.

WHY THIS EXISTS

The tasks in this repo are closed-world: every fact the agent needs is served by
the light-servers MCP sidecars or sits under the read-only /workspace/data mount.
A run that answers from the open web has not solved the task, it has looked up
something adjacent to it -- and it grades as though it had, because nothing
downstream can tell the two apart.

Harbor cannot prevent this on the docker provider, and it is worth being precise
about why, because the obvious fix does not work:

  network_mode = "no-network"   sets `network_mode: none` on the `main` service
                                (harbor/environments/docker/docker-compose-no-network.yaml),
                                which detaches the compose bridge too. The MCP
                                sidecars become unreachable, the agent starts
                                with ZERO tools, and the run grades 0.

  network_mode = "allowlist"    the docker provider declares
                                network_allowlist=False -- Harbor cannot express
                                a host allowlist on docker at all.

And the agent is Claude Code driven by CLAUDE_CODE_OAUTH_TOKEN, so it must keep
reaching api.anthropic.com regardless. There is no Harbor setting that means
"sidecars and the API, nothing else".

There is now a block, but it lives BELOW Harbor rather than in it:
services/egress-proxy/overlay.yaml is passed as --extra-docker-compose and makes
the compose project's default network `internal: true`, leaving a single squid
sidecar as the only route out with api.anthropic.com as its whole allowlist.
That is the distinction Harbor's network_mode cannot draw -- network_mode says
whether the container has a network, the overlay says where that network may go.

This scanner stays anyway, and stays blocking. Prevention is configuration and
configuration regresses quietly: an overlay that stopped being passed,
NETWORK_ISOLATION_OFF exported in a shell weeks ago, an allowlist widened to get
one run unstuck. The trajectory is the only artifact that records what the model
actually reached, so it remains the thing that decides whether a run ships. The
posture is PREVENT AND DETECT:
the container keeps working network, and any use of it by the MODEL is caught
from the recorded trajectory and blocks the run.

WHAT COUNTS

Only the agent's own tool calls are scanned. Claude Code's API traffic never
appears in a trajectory, so it is out of scope by construction rather than by
allowlist -- there is no rule here that could accidentally start permitting it.

Two families are caught:

  web tools       WebSearch / WebFetch, straight off the tool name.
  shell egress    Bash commands that fetch (curl, wget, nc, ssh, git clone) or
                  install (pip, npm, apt-get, ...), which cannot work without
                  the network.

Traffic aimed at the sidecars is NOT egress and must not be flagged: health
probes like `curl -s http://light-servers:9142/mcp` are a normal part of these
bundles. Fetchers are therefore judged by their TARGET HOST, and only hosts
outside INTERNAL_HOSTS count. Installers carry no host, so they are judged by
whether they are pinned to something local (--no-index, a path operand).
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

# Reachable over the compose bridge, not over the internet. A curl at any of
# these is the bundle working as designed.
INTERNAL_HOSTS = {
    "light-servers", "localhost", "127.0.0.1", "0.0.0.0", "::1",
    "main", "host.docker.internal",
}

# Tool names that are internet access by definition -- no argument inspection
# can make them local.
WEB_TOOLS = {"WebSearch", "WebFetch"}

# Shell verbs that move bytes to or from a host named on the command line.
FETCHERS = {
    "curl", "wget", "nc", "ncat", "netcat", "telnet",
    "ssh", "scp", "sftp", "rsync", "ftp", "svn",
}

# Shell verbs that reach a package index. No host on the command line, so these
# are judged by their flags instead.
INSTALLERS = {
    ("pip", "install"), ("pip3", "install"), ("uv", "pip"), ("uv", "add"),
    ("npm", "install"), ("npm", "i"), ("npm", "ci"), ("yarn", "add"),
    ("pnpm", "add"), ("pnpm", "install"), ("npx", ""),
    ("apt", "install"), ("apt-get", "install"), ("apk", "add"),
    ("yum", "install"), ("dnf", "install"), ("brew", "install"),
    ("gem", "install"), ("cargo", "install"), ("go", "get"),
}

# Flags that pin an installer to something already on disk. `pip install
# --no-index ./wheel` touches no index and is not egress.
OFFLINE_FLAGS = {"--no-index", "--offline", "--frozen", "--cached", "--no-download"}

# git only reaches the network for these; `git status` and `git log` do not.
GIT_NETWORK_SUBCOMMANDS = {"clone", "fetch", "pull", "push", "remote", "ls-remote", "submodule"}

# Network access smuggled through an interpreter. Matched on the source text of
# a `python3 -c` / `node -e` payload rather than on the command name, which is
# why these are substrings and not verbs.
INLINE_NETWORK_HINTS = (
    "urllib.request", "urllib2", "requests.get", "requests.post", "requests.request",
    "httpx.", "aiohttp", "socket.create_connection", "http.client",
    "urlopen", "fetch(", "XMLHttpRequest",
)

URL_RE = re.compile(r"\b(?:https?|ftp|ssh)://([^\s/'\"\\)>;|]+)", re.I)

FINDINGS: list[dict] = []


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


def flag(step: int, tool: str, kind: str, detail: str, evidence: str) -> None:
    FINDINGS.append(
        {"step": step, "tool": tool, "kind": kind, "detail": detail,
         "evidence": evidence[:400]}
    )


def host_of(token: str) -> str | None:
    """Hostname a fetcher operand points at, or None if it names no host."""
    m = URL_RE.search(token)
    if m:
        return m.group(1).split("@")[-1].split(":")[0].lower()
    # scp/ssh shorthand: user@host:/path, or a bare host operand.
    if "@" in token and ":" in token.split("@", 1)[1]:
        return token.split("@", 1)[1].split(":", 1)[0].lower()
    return None


def is_internal(host: str) -> bool:
    if host in INTERNAL_HOSTS:
        return True
    # Compose service aliases and loopback ranges are internal by construction.
    return host.startswith("127.") or host.endswith(".local") or host.endswith(".internal")


def scan_command(step: int, cmd: str) -> None:
    """Judge one shell command. Split on separators so `ls && curl x` is seen."""
    if not cmd.strip():
        return

    # Any absolute URL in the command is the strongest signal available, and it
    # survives quoting that would defeat the token walk below.
    for m in URL_RE.finditer(cmd):
        host = m.group(1).split("@")[-1].split(":")[0].lower()
        if not is_internal(host):
            flag(step, "Bash", "external-url", f"command references {host}", cmd)

    for hint in INLINE_NETWORK_HINTS:
        if hint in cmd:
            flag(step, "Bash", "inline-network",
                 f"interpreter payload uses {hint}", cmd)

    # Walk the command as tokens so we can read verbs and their flags. A command
    # we cannot lex is reported rather than skipped: silently passing an
    # unparseable command would be the one hole worth having none of.
    try:
        tokens = shlex.split(cmd, comments=True)
    except ValueError:
        flag(step, "Bash", "unparseable",
             "command could not be lexed; not provably local", cmd)
        return

    segments: list[list[str]] = [[]]
    for tok in tokens:
        if tok in ("&&", "||", ";", "|"):
            segments.append([])
        else:
            segments[-1].append(tok)

    for seg in segments:
        if not seg:
            continue
        verb = Path(seg[0]).name.lower()
        args = seg[1:]

        if verb in FETCHERS:
            hosts = [h for h in (host_of(a) for a in args) if h]
            external = [h for h in hosts if not is_internal(h)]
            if external:
                flag(step, "Bash", "fetch",
                     f"{verb} to {', '.join(sorted(set(external)))}", cmd)
            elif not hosts:
                # curl with no parseable host still ran a fetcher; report it
                # rather than assume it was local.
                flag(step, "Bash", "fetch",
                     f"{verb} with no resolvable host operand", cmd)

        if verb == "git" and args and args[0].lower() in GIT_NETWORK_SUBCOMMANDS:
            flag(step, "Bash", "vcs-network", f"git {args[0]}", cmd)

        for tool, sub in INSTALLERS:
            if verb != tool:
                continue
            if sub and not (args and args[0].lower() == sub):
                continue
            if any(f in args for f in OFFLINE_FLAGS):
                continue
            flag(step, "Bash", "package-install",
                 f"{verb} {sub}".strip() + " reaches a package index", cmd)
            break


def normalise(traj: dict) -> list[tuple[int, str, dict]]:
    """Both trajectory shapes this repo produces, flattened to (step, tool, args).

    tests/test.sh writes {"steps":[{"tool","arguments"}]} for the verifier, while
    Harbor publishes agent/trajectory.json as {"steps":[{"tool_calls":[...]}]}.
    Accepting both means this runs identically inside the verifier and on the
    host against a finished trial.
    """
    out: list[tuple[int, str, dict]] = []
    for i, step in enumerate(traj.get("steps") or [], start=1):
        if not isinstance(step, dict):
            continue
        if step.get("tool"):
            out.append((i, str(step["tool"]), step.get("arguments") or {}))
        for call in step.get("tool_calls") or []:
            if isinstance(call, dict):
                name = call.get("function_name") or call.get("name") or ""
                out.append((i, str(name), call.get("arguments") or {}))
    return out


def scan(traj: dict) -> None:
    for step, tool, args in normalise(traj):
        base = tool.split("__")[-1] if tool.startswith("mcp__") else tool

        if tool in WEB_TOOLS or base in WEB_TOOLS:
            target = args.get("url") or args.get("query") or ""
            flag(step, tool, "web-tool", f"{tool} called", str(target))
            continue

        if base == "Bash" or tool == "Bash":
            scan_command(step, str(args.get("command") or ""))


def _collapse() -> None:
    """One command, one finding.

    A `curl https://host/x` legitimately trips both the URL sweep and the token
    walk, and `git clone <url>` trips the URL sweep as well as the vcs rule. Both
    describe the same act, so the generic `external-url` finding is dropped when
    a more specific rule already fired on the same command -- the report should
    read as a list of things the model did, not a list of rules that matched.
    """
    specific = {(f["step"], f["evidence"]) for f in FINDINGS
                if f["kind"] != "external-url"}
    FINDINGS[:] = [f for f in FINDINGS
                   if f["kind"] != "external-url"
                   or (f["step"], f["evidence"]) not in specific]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("trajectory", type=Path)
    ap.add_argument("--json", type=Path, help="write findings here for grading")
    ap.add_argument("--warn-only", action="store_true",
                    help="report findings but exit 0 (does not block the run)")
    a = ap.parse_args(argv)

    if not a.trajectory.is_file():
        # No trajectory is not evidence of good behaviour, but it is also not
        # evidence of bad. The aborted-trial guard in run_task.sh already fails
        # loudly on a run that produced nothing, so this stays out of its way.
        print(f"  {_c('33', 'warn')}  no trajectory at {a.trajectory}; nothing to audit")
        return 0

    try:
        traj = json.loads(a.trajectory.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  {_c('31', 'FAIL')}  trajectory does not parse: {exc}")
        return 2

    scan(traj)
    total = len(normalise(traj))
    _collapse()

    print(f"== internet use audit: {a.trajectory} ==")
    if not FINDINGS:
        print(f"  {_c('32', 'ok')}    {total} tool call(s), no internet access")
    else:
        for f in FINDINGS:
            print(f"  {_c('31', 'FAIL')}  step {f['step']}: [{f['kind']}] {f['detail']}")
            print(f"        {f['evidence'].splitlines()[0][:160]}")

    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(
            {"used_internet": bool(FINDINGS), "tool_calls": total,
             "findings": FINDINGS}, indent=2))

    if FINDINGS and not a.warn_only:
        print(f"\n  blocked: the model used the internet "
              f"({len(FINDINGS)} finding(s)); this task is closed-world.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
