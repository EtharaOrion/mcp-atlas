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
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# THE RULES THEMSELVES LIVE IN egress_rules.py
#
# They used to live here, and that was correct while this audit was the only
# thing reading them. It stopped being correct when the run began DENYING a
# command as well as reporting it: the PreToolUse hook shipped into the
# container (tools/network/egress_rules.py, hook mode) has to agree with this
# file exactly, and two copies of "what counts as egress" drift in the
# expensive direction -- a command the hook allows and this audit later blocks
# costs a whole graded run, discarded after the fact for something that could
# have been refused in the turn it was typed.
#
# So the classification is imported, never redefined. What stays here is the
# half that needs an OUTCOME rather than an intention: the proxy log, the
# install-success markers, and the reporting.
#
# sys.path, not a package import: this file is run as a script by
# scripts/run_task.sh and by its tests, so `tools.network` is not importable.
# --------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))

from egress_rules import (            # noqa: E402
    GIT_NETWORK_SUBCOMMANDS,
    HEREDOC_RE,
    INLINE_NETWORK_HINTS,
    INSTALLERS,
    INTERNAL_HOSTS,
    NAMESPACE_URI_PREFIXES,
    OFFLINE_FLAGS,
    URL_RE,
    WEB_TOOLS,
    classify_tool,
    host_of,
    is_internal,
)

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
    # apt again, and the reason it is here: `apt-get install -y -q chromium
    # 2>&1 | tail -3` keeps exactly these trigger lines and cuts every "Setting
    # up" line above them. A real run installed chromium that way and the audit
    # reported only an attempt. dpkg runs triggers when a package's files have
    # actually been unpacked onto the disk, so the line means the same thing.
    re.compile(r"^\s*Processing triggers for\s+\S", re.M),
    re.compile(r"^\s*Unpacking\s+\S+\s+\(", re.M),                   # apt, mid-install
    re.compile(r"^\s*Get:\d+\s+https?://", re.M),                    # apt, fetching from a mirror
    # pip's self-check asks PyPI which version of pip is current and prints
    # this. It is not an install marker and it is deliberately weaker than the
    # others -- but install_landed() is only ever consulted on a command that
    # ALREADY produced an installer finding, so this can strengthen a finding
    # and can never invent one. `pip install --quiet Pillow 2>&1 | tail -2`
    # printed nothing else, and this was the only surviving proof of reach.
    re.compile(r"^\s*\[notice\].*new release of pip is available", re.M),
    re.compile(r"^\(\d+/\d+\)\s+Installing\s+\S", re.M),            # apk
    re.compile(r"^\s*Downloaded\s+\S+\s+v?\d", re.M),               # cargo
    re.compile(r"^\s*go: downloading\s+\S", re.M),                   # go get
    re.compile(r"^==>\s+Pouring\s+\S", re.M),                        # brew
)


FINDINGS: list[dict] = []

# Whether this audit saw an agent trajectory at all. An aborted trial -- the
# environment died, agent setup failed -- leaves a proxy log and no trajectory,
# and traffic in that log was made by harbor's own setup, before the model ran.
# Blaming the MODEL for it reads as agent misbehaviour and sends an operator
# looking at a transcript that does not exist.
HAD_TRAJECTORY = True

# How many tool calls the trajectory held. Separate from HAD_TRAJECTORY because
# a trajectory can exist, parse, and still record nothing the agent did: a
# recorded run died on its first model call with "Weekly/Monthly Limit
# Exhausted" and published two steps, a prompt and an error. The audit printed
# "ok  0 tool call(s), no internet access" -- a green tick on a run that never
# happened -- and the trial still counted as an attempt, halving the job's mean
# reward. Neither is an internet finding, so neither blocks; both need saying.
TOOL_CALLS = 0


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


def flag(step: int | None, tool: str, kind: str, detail: str, evidence: str,
         *, suppressed: bool = False) -> None:
    """step is None for findings that come from the proxy log rather than a
    trajectory step -- they are real findings and must block, but they have no
    step number to point at.

    `suppressed` marks a command that piped its own output away, so the absence
    of an install-success marker proves nothing. _outcome() reads it.
    """
    record = {"step": step, "tool": tool, "kind": kind, "detail": detail,
              "evidence": evidence[:400]}
    if suppressed:
        record["evidence_suppressed"] = True
    FINDINGS.append(record)



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
        if not m:
            continue
        # Anchor on m.end(), never m.start(). Every marker opens with `^\s*`,
        # and under re.M that `\s*` happily consumes the NEWLINE that ended the
        # previous line -- so m.start() points at that newline, `find("\n",
        # m.start())` returns the very same index, and the slice is "". Empty
        # is falsy, the caller read it as "no proof", and a real
        # `added 102 packages in 38s` was reported as a mere attempt. m.end()
        # is always inside the matched text, so the line it sits on is the line
        # that actually carries the evidence.
        line_start = text.rfind("\n", 0, m.end()) + 1
        line_end = text.find("\n", m.end())
        return text[line_start:line_end if line_end != -1 else len(text)].strip()
    return None



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
    """Turn every tool call in the trajectory into findings.

    The rules are egress_rules.classify_tool()'s, unchanged -- what this adds is
    the OUTCOME, which only the audit is in a position to know. An installer
    finding arrives here as "the model reached for an index"; the step's own
    output is then read to decide whether it got there:

      package-installed   the output proves it landed. Ground truth of reach,
                          in the same class as an allowlist breach in the proxy
                          log, and unlike that log it survives a run with no
                          proxy to corroborate against.
      package-install     no proof either way. The weaker claim, and the honest
                          one when a denied install printed a 403 and stopped.

    A SUPPRESSED install is the third case, and it is the one that cost a real
    run. `apt-get install -y -q chromium 2>&1 | tail -3` keeps the last three
    lines -- "Processing triggers for libc-bin" -- and drops every "Setting up"
    line above them, so the markers find nothing and the strongest available
    evidence reads as absent. Absent is not negative, so the flag is carried
    onto the finding and _outcome() decides what it means: with a proxy log,
    squid is the witness and settles it; without one, nothing could have stopped
    the install and the agent removed the only other record of it.
    """
    for step, tool, args, response in normalise(traj):
        cmd = str(args.get("command") or "") if tool.split("__")[-1] == "Bash" else ""
        for f in classify_tool(tool, args):
            evidence = cmd or str(args.get("url") or args.get("query") or "")
            if f.kind != "package-install":
                flag(step, tool, f.kind, f.detail, evidence)
                continue
            landed = install_landed(response)
            if landed:
                flag(step, tool, "package-installed",
                     f.detail.replace("reaches", "reached")
                     + " and the install SUCCEEDED",
                     f"{evidence}  ->  {landed}")
            else:
                flag(step, tool, "package-install", f.detail, evidence,
                     suppressed=f.suppressed)


def main(argv=None) -> int:
    global HAD_TRAJECTORY, TOOL_CALLS
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
    total = TOOL_CALLS = len(normalise(traj))

    # Deduplication happens per-command inside egress_rules.classify(), so proxy
    # findings are never folded into trajectory ones: a curl the scanner already
    # flagged AND a matching denial in the log are two independent observations
    # of the same attempt, and losing the second would cost the corroboration
    # the proxy log exists to add.
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
      "no-run"     a trajectory that parses and holds no tool calls. The agent
                   never acted, so there was nothing to audit and "clean" would
                   be a green tick on a run that did not happen.

    THE SUPPRESSED-INSTALL RULE, and why it is not the same as "unverified".

    An install whose output was piped away (`... | tail -3`) leaves no marker,
    and the absence of a marker is not evidence the install failed. What decides
    it is whether anything ELSE could have:

      with a proxy log     squid saw every packet. If it had let the index
                           through, that is an allowlist-breach line and the
                           first rule already returned "breach". It did not, so
                           the install was refused -- "denied" is the truth.
      with no proxy log    nothing was in the path to refuse it, and the command
                           removed the only other witness. Calling that
                           "unverified" understates a run that on any honest
                           reading fetched the package.
    """
    if any(f["kind"] in ("allowlist-breach", "package-installed") for f in FINDINGS):
        return "breach"
    if not FINDINGS:
        return "no-run" if HAD_TRAJECTORY and not TOOL_CALLS else "clean"
    if not HAD_TRAJECTORY:
        return "setup"
    if attempts:
        return "denied"
    if any(f.get("evidence_suppressed") for f in FINDINGS):
        return "breach"
    return "unverified"


_VERDICT_LINE = {
    "breach": "the model reached the open internet",
    "clean": "no internet access",
    "no-run": "the agent made no tool calls; there was nothing to audit",
    "setup": "traffic was attempted before the agent ran (harbor's agent setup) "
             "and denied; the model made no tool calls",
    "denied": "the model tried to reach the internet and every attempt was denied",
    "unverified": "the model tried to reach the internet (no proxy log -- "
                  "whether it succeeded is unverified)",
}


def _report(a, *, total: int, attempts: list[dict]) -> None:
    """Print the audit and write its JSON. Shared by both entry paths above."""
    print(f"== internet use audit: {a.trajectory} ==")
    if not FINDINGS and HAD_TRAJECTORY and not total:
        # Not a finding and not a block -- an empty trajectory is not
        # misbehaviour. But it must not print as a clean audit either: the run
        # this was written for died on its first model call, made no tool calls,
        # and was reported as "ok  0 tool call(s), no internet access".
        print(f"  {_c('33', 'INVALID')}  the agent made no tool calls -- "
              f"nothing was audited, and this is NOT a clean run")
    elif not FINDINGS:
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
