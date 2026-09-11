#!/usr/bin/env python3
"""Detect whether the agent reached the public internet, and block the run if it did.

    tools/network/detect_internet_use.py <trajectory.json> [--json OUT] [--warn-only]
                                  [--access-log run_N/logs/egress-access.log]

Exit 0 = clean. Exit 2 = the model reached for the internet; the run is
blocked. Whether it got there is a separate question -- see _outcome().

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
tools/network/egress-proxy/overlay.yaml is passed as --extra-docker-compose and makes
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

An installer is judged twice. The command line says the model REACHED for a
package index; the command's OUTPUT says whether it got there. A denied
`pip install pandas` prints a proxy 403 and installs nothing, while the same
command on a leaked network prints "Successfully installed pandas-2.2.3" -- and
that difference is the difference between a block that worked and a benchmark
result that was never closed-world. Both block the run; only the second is
reported as a breach (see INSTALL_SUCCESS_MARKERS and _outcome).
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
# Hosts that never leave the compose bridge. Peer definition:
# tools/network/egress-proxy/overlay.yaml's NO_PROXY is the same set applied to the
# run rather than to the transcript, and squid.conf's comment makes keeping the
# two in agreement a standing pact.
#
# host.docker.internal is deliberately gone. It was half of the divergence
# scripts/tests/test_egress_allowlist.py carried as an xfail: this file called it
# internal, so a call to it passed the audit, while NO_PROXY omitted it, so the
# same call went to squid and took a 403. Reconciled in the direction the xfail
# recommended -- `internal: true` leaves the bridge with no gateway, so the
# host-gateway address has no route no matter what the proxy settings say. A
# trajectory call to it is a real failed egress attempt and belongs in findings.
#
# 0.0.0.0 was the OTHER half, and dropping it too was wrong. The xfail treated
# both as one case, but they are not: host.docker.internal names a route OFF the
# container, while 0.0.0.0 as a DESTINATION is a local bind address -- `curl
# 0.0.0.0:8000` against a server the agent just started is ordinary local work,
# not egress. Removing it made that a blocking finding, and is_internal() does
# not otherwise cover it (it matches 127.* and localhost, not 0.0.0.0). It is
# back here, and added to NO_PROXY to keep the pact whole; sending a bind address
# to the proxy was never useful anyway.
#
# Safe because this scanner reads TRAJECTORY TOOL CALLS only. The cc-bridge and
# zbridge do use host.docker.internal, but as the Claude Code process's own
# ANTHROPIC_BASE_URL -- that traffic is never a Bash step and never appears here.
INTERNAL_HOSTS = {
    "light-servers", "localhost", "127.0.0.1", "0.0.0.0", "::1", "main",
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

# Lines an installer prints only after it has actually pulled something from an
# index. These are read out of the STEP'S RESPONSE, which is the one place a
# trajectory records an outcome rather than an intention, and they are what
# lets this scanner say "the install landed" instead of "the model tried".
#
# Their weight: a confirmed install is ground truth of reach, in the same class
# as an allowlist breach in the proxy log, and unlike the proxy log it survives
# a NETWORK_ISOLATION_OFF=1 run where there is nothing to corroborate against.
#
# POSITIVE MARKERS ONLY, and the omissions are deliberate. pip's "Requirement
# already satisfied", npm's "up to date", apt's "0 newly installed" all mean the
# resolver found the package ALREADY ON DISK. Nothing left the container, so
# none of them may read as egress -- matching them would turn every warm-cache
# install into a false breach, which is the expensive direction to be wrong in.
INSTALL_SUCCESS_MARKERS = (
    re.compile(r"^\s*Successfully installed\s+\S", re.M),            # pip, gem
    re.compile(r"^\s*(?:Collecting|Downloading)\s+\S", re.M),        # pip, mid-install
    re.compile(r"^\s*(?:Installed|Prepared)\s+\d+\s+packages?", re.M),  # uv
    re.compile(r"^\s*added\s+\d+\s+packages?", re.M),               # npm
    re.compile(r"^\s*\+\s+\S+(?:@|==)\d", re.M),                     # npm/yarn/pnpm/uv per package
    re.compile(r"^\s*Setting up\s+\S+\s+\(", re.M),                  # apt / apt-get / dpkg
    re.compile(r"^\s*Get:\d+\s+https?://", re.M),                    # apt, fetching from a mirror
    re.compile(r"^\(\d+/\d+\)\s+Installing\s+\S", re.M),            # apk
    re.compile(r"^\s*Downloaded\s+\S+\s+v?\d", re.M),               # cargo
    re.compile(r"^\s*go: downloading\s+\S", re.M),                   # go get
    re.compile(r"^==>\s+Pouring\s+\S", re.M),                        # brew
)

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

# URLs that are IDENTIFIERS rather than addresses. XML namespaces are spelled
# as URLs by the spec and are never dereferenced: an SVG generator writes
# xmlns="http://www.w3.org/2000/svg" without a socket ever opening, and every
# .docx these bundles unpack is full of schemas.openxmlformats.org.
#
# Exempt from the bare URL SWEEP ONLY. A fetcher verb aimed at one of these
# hosts still trips the `fetch` rule, because `curl http://www.w3.org/x` is a
# real request whatever the host is famous for. That split is the whole point:
# the sweep is a string match and can afford to be wrong in the quiet
# direction; the verb rules cannot.
#
# Seen in the wild: a run was blocked because the agent printed
# `'http://www.w3.org/2000/svg'` while CHECKING ITS OWN OUTPUT had no external
# references. A false positive there costs a clean run; the miss it risks is a
# curl the verb rules catch anyway.
NAMESPACE_URI_PREFIXES = (
    "www.w3.org/1999/",
    "www.w3.org/2000/svg",
    "www.w3.org/2001/XMLSchema",
    "www.w3.org/XML/1998/",
    "schemas.openxmlformats.org/",
    "schemas.microsoft.com/",
    "purl.org/dc/",
)

_NAMESPACE_RE = re.compile(
    r"https?://(?:" + "|".join(re.escape(x) for x in NAMESPACE_URI_PREFIXES) + ")"
)

URL_RE = re.compile(r"\b(?:https?|ftp|ssh)://([^\s/'\"\\)>;|]+)", re.I)

# `cmd << EOF` / `cmd <<-'EOF'` / `cmd <<"EOF"`. The delimiter is group 2; the
# quoting around it only decides whether the shell expands the body, which is
# not this tool's business.
HEREDOC_RE = re.compile(r"<<[-~]?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

FINDINGS: list[dict] = []

# Whether this audit saw an agent trajectory at all. An aborted trial -- the
# environment died, agent setup failed -- leaves a proxy log and no trajectory,
# and traffic in that log was made by harbor's own setup, before the model ran.
# Blaming the MODEL for it reads as agent misbehaviour and sends an operator
# looking at a transcript that does not exist.
HAD_TRAJECTORY = True


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


def flag(step: int | None, tool: str, kind: str, detail: str, evidence: str) -> None:
    """step is None for findings that come from the proxy log rather than a
    trajectory step -- they are real findings and must block, but they have no
    step number to point at."""
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


# --------------------------------------------------------------------------
# PROXY GROUND TRUTH
#
# Everything above infers egress from the TRAJECTORY: tool names and shell verbs
# in the transcript. That inference has a floor. `requests.get(...)` inside a
# python heredoc carries no verb this scanner knows, and a trajectory that was
# truncated or never written carries nothing at all.
#
# squid's access.log is the other half: not what the model said it would do, but
# what actually arrived at the proxy and what the proxy did about it. It is
# written per attempt into the trial's agent-log dir (tools/network/egress-proxy/
# entrypoint.sh) and reaches the run dir via tools/delivery/harbor_to_output.py.
# --------------------------------------------------------------------------

# The one host squid lets out. tools/network/egress-proxy/squid.conf is the source of
# truth and scripts/tests/test_egress_allowlist.py::EXPECTED_ALLOWLIST pins it
# there; this is the third copy, so change one and look at the other two.
PROXY_ALLOWLIST = {"api.anthropic.com"}

# Hosts the Claude Code CLI reaches on its own initiative -- update checks,
# feature flags, telemetry, error reporting. squid denies all of them, which is
# correct, but the MODEL did not ask for them and a run must not be blocked for
# the CLI clearing its throat. Enumerated in squid.conf's allowlist comment.
#
# overlay.yaml sets CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1, which stops most
# of this at the source, so in practice these lines are rare. They are listed
# anyway because a version bump can add one, and the failure mode of NOT listing
# it is a benchmark that refuses to deliver a clean run.
#
# TELEMETRY ONLY. Every host here is infrastructure that carries no content: an
# update check, a feature-flag fetch, a crash report. A denial to one of them
# says nothing about the model, so it is recorded and does not block.
#
# raw.githubusercontent.com is deliberately NOT here, though squid.conf lists it
# among the hosts the CLI reaches. It serves CONTENT -- a place to fetch
# instructions from or park data at -- and a denial there is exactly the event a
# closed-world benchmark wants to hear about. Classifying it as infrastructure
# would make the audit silent on the most useful denial it could ever show.
#
# The cost is a possible false positive, if the CLI fetches it unprompted
# despite CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1. That is the right way
# round: a false positive is loud, lands in internet_audit.json with the
# offending line attached, and is cleared with INTERNET_AUDIT_WARN=1 while
# someone decides. A false negative is silent and ships a benchmark result that
# was never actually checked. Same posture as squid.conf's "add a host here only
# after seeing it denied in access.log".
CLI_INFRA_HOSTS = {
    "platform.claude.com", "claude.ai", "statsig.anthropic.com",
    "downloads.claude.ai",
}

CLI_INFRA_SUFFIXES = (".datadoghq.com", ".statsig.com", ".sentry.io")

# squid native format, whitespace separated:
#   ts elapsed client CODE/STATUS bytes METHOD URL rfc931 hierarchy type
# Field 3 is the result code, 5 the method, 6 the URL (host:port for CONNECT).
_ACCESS_MIN_FIELDS = 7


def _access_host(url: str) -> str:
    """Host from an access.log URL field. CONNECT logs host:port, GET logs a URL."""
    if "://" in url:
        url = url.split("://", 1)[1]
    return url.split("/", 1)[0].rsplit(":", 1)[0].strip("[]").lower()


def _is_cli_infra(host: str) -> bool:
    return host in CLI_INFRA_HOSTS or host.endswith(CLI_INFRA_SUFFIXES)


def scan_access_log(path: Path) -> list[dict]:
    """Parse squid's log; flag the attempts the model is answerable for.

    Returned records go into the audit JSON whole -- including the allowed ones,
    because "api.anthropic.com was reached N times and nothing else was" is the
    positive evidence that the block was live for this run, which no amount of
    config assertion can supply.
    """
    attempts: list[dict] = []
    for line in path.read_text(errors="replace").splitlines():
        f = line.split()
        if len(f) < _ACCESS_MIN_FIELDS or "/" not in f[3]:
            continue
        code = f[3].split("/", 1)[0]
        status = f[3].split("/", 1)[1]
        method, url = f[5], f[6]
        host = _access_host(url)
        if not host:
            continue
        denied = code.endswith("_DENIED") or status in ("403", "407")
        rec = {"host": host, "method": method, "code": f[3], "denied": denied}
        attempts.append(rec)

        if _is_cli_infra(host):
            rec["verdict"] = "cli_infrastructure"
            continue
        if not denied and host not in PROXY_ALLOWLIST:
            # The allowlist did not hold. Worse than a denial: something left.
            rec["verdict"] = "ALLOWLIST_BREACH"
            flag(None, "egress-proxy", "allowlist-breach",
                 f"{host} was NOT denied by the proxy but is not on the allowlist",
                 line)
            continue
        if denied:
            # The model tried. The auditor already treats attempts as findings
            # regardless of outcome -- a WebFetch call counts whether or not it
            # returned -- so a denial is a finding, not an all-clear.
            rec["verdict"] = "blocked_attempt"
            flag(None, "egress-proxy", "proxy-denied",
                 f"{method} {host} was attempted and denied by the egress proxy",
                 line)
            continue
        rec["verdict"] = "allowed"
    return attempts


def response_text(resp) -> str:
    """A step's response as searchable text.

    Trajectories carry it three ways: a plain string (Bash stdout, the case that
    matters here), a parsed JSON object (agent_log_to_trajectory.py json.loads
    the tool_result when it can), or nothing at all. Nested containers are
    flattened by joining their string leaves on newlines rather than dumping
    them -- json.dumps would escape every newline and defeat the line anchors
    in INSTALL_SUCCESS_MARKERS, which is what keeps them from matching mid-line
    prose.
    """
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        return "\n".join(response_text(v) for v in resp.values())
    if isinstance(resp, (list, tuple)):
        return "\n".join(response_text(v) for v in resp)
    return str(resp)


def install_landed(resp) -> str | None:
    """The line proving a package was actually fetched and installed, or None.

    Returns the evidence rather than a bool: a finding that makes the stronger
    claim has to be able to show the line it made it from, or an operator
    cannot tell a real breach from a marker that matched something else.

    No response is NOT a failed install. A trajectory can be truncated, and a
    tool result can be missing for reasons that have nothing to do with the
    network, so absence falls back to the weaker attempt finding.
    """
    text = response_text(resp)
    if not text:
        return None
    for pat in INSTALL_SUCCESS_MARKERS:
        m = pat.search(text)
        if m:
            end = text.find("\n", m.start())
            return text[m.start():end if end != -1 else len(text)].strip()
    return None


def split_heredocs(cmd: str) -> tuple[str, list[str]]:
    """Split `cmd` into (the shell to lex, the heredoc bodies lifted out of it).

    A heredoc body is data being fed to a program, not shell words. shlex is a
    POSIX word lexer with no heredoc rule, so it reads the body as ordinary
    shell text and the first apostrophe or triple-quote in it raises "No
    closing quotation" -- which scan_command's fail-closed branch then turns
    into a blocking finding. `python3 - <<'PY' ... PY` is how an agent writes
    most of its multi-line edits, so that fired on ordinary local work.

    The bodies are returned rather than dropped: they are still audited, by the
    raw-command sweeps in scan_command and by scan_heredoc_body.
    """
    if "<<" not in cmd:
        return cmd, []
    lines = cmd.split("\n")
    kept: list[str] = []
    bodies: list[str] = []
    i = 0
    while i < len(lines):
        kept.append(lines[i])
        line = lines[i]
        i += 1
        # One line can open several bodies (`cmd <<A <<B`); they arrive in the
        # order the redirections were written.
        for m in HEREDOC_RE.finditer(line):
            delim = m.group(2)
            body: list[str] = []
            while i < len(lines) and lines[i].strip() != delim:
                body.append(lines[i])
                i += 1
            i += 1          # the terminator line, or one past the last line
            bodies.append("\n".join(body))
    return "\n".join(kept), bodies


def scan_heredoc_body(step: int, body: str, cmd: str, response=None) -> None:
    """Audit a lifted heredoc body with the same verb walk as the command line.

    A body fed to `bash` is shell, and dropping it would hand the model a place
    to keep a `pip install` where nothing looks. So each line is lexed on its
    own -- line by line because shlex does not treat a newline as a separator,
    and a whole body lexed at once collapses into a single run-on segment whose
    first word is the only verb anyone reads.

    A line that will not lex is skipped rather than flagged. Bodies are usually
    not shell at all (a Python payload, a file being written), and there the
    quoting that defeats shlex is just the payload's own syntax. That is not the
    hole it looks like: URL_RE and INLINE_NETWORK_HINTS already ran over the raw
    command with its bodies intact, so an `http://` or a `urlopen` in there is
    caught whatever the body turns out to be.
    """
    for line in body.split("\n"):
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            continue
        walk_segments(step, tokens, cmd, response)


def walk_segments(step: int, tokens: list[str], cmd: str, response=None) -> None:
    """Read verbs and their flags out of one lexed command.

    Split on separators so `ls && curl x` is seen. `cmd` is the raw command the
    tokens came from -- it is the evidence a finding shows, and it is what
    _collapse keys on, so it stays the whole command even when the tokens are
    one line of a heredoc body inside it.
    """
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
            name = f"{verb} {sub}".strip()
            landed = install_landed(response)
            if landed:
                # Same act as the line below, stronger claim, so it is reported
                # ONCE under the name that says what actually happened -- the
                # report is a list of what the model did, not of rules matched.
                flag(step, "Bash", "package-installed",
                     f"{name} reached a package index and the install SUCCEEDED",
                     f"{cmd}  ->  {landed}")
            else:
                flag(step, "Bash", "package-install",
                     f"{name} reaches a package index", cmd)
            break


def scan_command(step: int, cmd: str, response=None) -> None:
    """Judge one shell command. Split on separators so `ls && curl x` is seen.

    `response` is what the command printed, and it is consulted for one thing:
    telling an install that reached an index from one that was refused.
    """
    if not cmd.strip():
        return

    # Any absolute URL in the command is the strongest signal available, and it
    # survives quoting that would defeat the token walk below.
    for m in URL_RE.finditer(cmd):
        if _NAMESPACE_RE.match(cmd, m.start()):
            continue
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
    #
    # Heredoc bodies come out first -- see split_heredocs for why leaving them
    # in made that fail-closed branch fire on benign local edits -- and are
    # audited on their own terms.
    lex_src, heredoc_bodies = split_heredocs(cmd)
    for body in heredoc_bodies:
        scan_heredoc_body(step, body, cmd, response)
    try:
        tokens = shlex.split(lex_src, comments=True)
    except ValueError:
        flag(step, "Bash", "unparseable",
             "command could not be lexed; not provably local", cmd)
        return

    walk_segments(step, tokens, cmd, response)


def normalise(traj: dict) -> list[tuple[int, str, dict, object]]:
    """Both trajectory shapes the repo produces, flattened to (step, tool, args, response).

    tests/test.sh writes {"steps":[{"tool","arguments","response"}]} for the
    verifier, while Harbor publishes agent/trajectory.json as
    {"steps":[{"tool_calls":[...],"observation":{"results":[...]}}]}. Accepting
    both means a run audits identically inside the verifier and on the host
    against a finished trial.

    The RESPONSE is carried because it is the only record of what a command
    achieved rather than what it asked for -- it is what tells a denied
    `pip install` from one that landed. It is whatever the trajectory holds
    (string, parsed JSON, or None); response_text() does the flattening.
    """
    out: list[tuple[int, str, dict, object]] = []
    for i, step in enumerate(traj.get("steps") or [], start=1):
        if not isinstance(step, dict):
            continue
        if step.get("tool"):
            out.append((i, str(step["tool"]), step.get("arguments") or {},
                        step.get("response")))
        # Harbor keeps the result out of the call and joins the two by id:
        # observation.results[].source_call_id == tool_calls[].tool_call_id.
        # A step can carry several calls and their results in either order, so
        # index first and look up second rather than zipping positionally.
        results: dict = {}
        obs = step.get("observation")
        if isinstance(obs, dict):
            for r in obs.get("results") or []:
                if isinstance(r, dict):
                    results[r.get("source_call_id")] = r.get("content")
        for call in step.get("tool_calls") or []:
            if isinstance(call, dict):
                name = call.get("function_name") or call.get("name") or ""
                out.append((i, str(name), call.get("arguments") or {},
                            results.get(call.get("tool_call_id"))))
    return out


def scan(traj: dict) -> None:
    for step, tool, args, response in normalise(traj):
        base = tool.split("__")[-1] if tool.startswith("mcp__") else tool

        if tool in WEB_TOOLS or base in WEB_TOOLS:
            target = args.get("url") or args.get("query") or ""
            flag(step, tool, "web-tool", f"{tool} called", str(target))
            continue

        if base == "Bash" or tool == "Bash":
            scan_command(step, str(args.get("command") or ""), response)


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
    global HAD_TRAJECTORY
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("trajectory", type=Path)
    ap.add_argument("--json", type=Path, help="write findings here for grading")
    ap.add_argument("--warn-only", action="store_true",
                    help="report findings but exit 0 (does not block the run)")
    ap.add_argument("--access-log", type=Path,
                    help="squid access.log for this run; adds proxy ground truth "
                         "to the trajectory inference")
    a = ap.parse_args(argv)

    if not a.trajectory.is_file():
        # No trajectory is not evidence of good behaviour, but it is also not
        # evidence of bad. The aborted-trial guard in run_task.sh already fails
        # loudly on a run that produced nothing, so this stays out of its way.
        # A missing trajectory is not evidence of good behaviour -- and if the
        # proxy log survived, it is the better witness anyway. Audit it alone
        # rather than returning a clean bill for a run nobody can see.
        HAD_TRAJECTORY = False
        print(f"  {_c('33', 'warn')}  no trajectory at {a.trajectory}")
        if not (a.access_log and a.access_log.is_file()):
            return 0
        attempts = scan_access_log(a.access_log)
        _report(a, total=0, attempts=attempts)
        if FINDINGS and not a.warn_only:
            # Say WHOSE traffic it was. This path has no trajectory by
            # definition, so the words here are the only thing standing between
            # an operator and a hunt through a transcript that does not exist.
            print(f"\n  blocked: {_VERDICT_LINE[_outcome(attempts)]} "
                  f"({len(FINDINGS)} finding(s)); this task is closed-world.")
            return 2
        return 0

    try:
        traj = json.loads(a.trajectory.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  {_c('31', 'FAIL')}  trajectory does not parse: {exc}")
        return 2

    scan(traj)
    total = len(normalise(traj))
    _collapse()

    # After _collapse(), so proxy findings are never deduplicated against
    # trajectory ones: a curl the scanner already flagged AND a matching denial
    # in the log are two independent observations of the same attempt, and
    # losing the second would cost the corroboration this flag exists to add.
    attempts = []
    if a.access_log:
        if a.access_log.is_file():
            attempts = scan_access_log(a.access_log)
        else:
            print(f"  {_c('33', 'warn')}  no proxy log at {a.access_log}; "
                  f"trajectory-only audit")

    _report(a, total=total, attempts=attempts)

    if FINDINGS and not a.warn_only:
        print(f"\n  blocked: {_VERDICT_LINE[_outcome(attempts)]} "
              f"({len(FINDINGS)} finding(s)); this task is closed-world.")
        return 2
    return 0


def _outcome(attempts: list[dict]) -> str:
    """Did anything actually REACH the open web, or was it only attempted?

    The distinction is not cosmetic. A denied attempt means the egress proxy
    did its job; reporting it as "the model used the internet" describes a
    working defence as a breach, and an operator reading that line goes looking
    for a leak that never happened.

      "breach"     something got out. Two independent witnesses can say so: an
                   allowlist-breach line in the proxy log (a host that was NOT
                   denied and is NOT on the allowlist), or a package-installed
                   finding (a command whose own output shows an index was
                   reached and a package fetched). Either is sufficient -- the
                   second is what still speaks on a run with no proxy log.
      "clean"      no findings at all. Stated explicitly because the caller
                   aggregates this field across runs, and a run with nothing to
                   report must not land in that aggregate wearing one of the
                   words below.
      "setup"      findings, but no trajectory to attribute them to: the agent
                   never ran, so this is harbor's setup traffic, not the model.
      "denied"     a proxy log was read and carries no breach, so squid's own
                   record is ground truth that every attempt was refused.
      "unverified" no proxy log (NETWORK_ISOLATION_OFF=1, or capture broken).
                   The trajectory shows the attempt; nothing shows the outcome,
                   and on an open network the attempt most likely succeeded.
                   Never call this "denied" -- that is the claim we cannot make.
    """
    if any(f["kind"] in ("allowlist-breach", "package-installed") for f in FINDINGS):
        return "breach"
    if not FINDINGS:
        return "clean"
    if not HAD_TRAJECTORY:
        return "setup"
    return "denied" if attempts else "unverified"


_VERDICT_LINE = {
    "breach": "the model reached the open internet",
    "clean": "no internet access",
    "setup": "traffic was attempted before the agent ran (harbor's agent setup) "
             "and denied; the model made no tool calls",
    "denied": "the model tried to reach the internet and every attempt was denied",
    "unverified": "the model tried to reach the internet (no proxy log -- "
                  "whether it succeeded is unverified)",
}


def _report(a, *, total: int, attempts: list[dict]) -> None:
    """Print the audit and write its JSON. Shared by both entry paths above."""
    print(f"== internet use audit: {a.trajectory} ==")
    if not FINDINGS:
        print(f"  {_c('32', 'ok')}    {total} tool call(s), no internet access")
    else:
        for f in FINDINGS:
            where = "proxy" if f["step"] is None else f"step {f['step']}"
            print(f"  {_c('31', 'FAIL')}  {where}: [{f['kind']}] {f['detail']}")
            print(f"        {f['evidence'].splitlines()[0][:160]}")

    if attempts:
        # The positive half of the record. An allowed line to api.anthropic.com
        # is proof the proxy was in the path at all -- a log with no allowed
        # lines and no denials means the capture is broken, not that the run
        # was clean, and only printing the counts makes that visible.
        allowed = sum(1 for r in attempts if not r["denied"])
        denied = sum(1 for r in attempts if r["denied"])
        infra = sum(1 for r in attempts if r.get("verdict") == "cli_infrastructure")
        print(f"  {_c('32', 'ok')}    proxy log: {len(attempts)} request(s), "
              f"{allowed} allowed, {denied} denied ({infra} CLI infrastructure)")

    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(
            {"used_internet": bool(FINDINGS), "outcome": _outcome(attempts),
             "tool_calls": total,
             "findings": FINDINGS, "proxy_attempts": attempts}, indent=2))


if __name__ == "__main__":
    sys.exit(main())
