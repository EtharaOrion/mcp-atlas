"""The PreToolUse egress guard -- the layer the model can actually read.

Three properties, and the third is the one that makes the other two worth
having:

  1. the hook refuses egress and lets local work through;
  2. it fails OPEN, because the routing table is the enforcement boundary and a
     bug here must not be able to kill every Bash call in a run;
  3. it and tools/network/detect_internet_use.py agree, on every command, always
     -- they import the same rules, and a test says so out loud, because a
     command the hook allows and the audit later blocks costs a whole graded run.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RULES = REPO / "tools" / "network" / "egress_rules.py"
MAKE_SETTINGS = REPO / "tools" / "network" / "make_guard_settings.py"
DETECT = REPO / "tools" / "network" / "detect_internet_use.py"


def hook(tool_name: str, tool_input: dict) -> subprocess.CompletedProcess:
    """Run the guard exactly as Claude Code does: payload on stdin."""
    return subprocess.run(
        [sys.executable, str(RULES)],
        input=json.dumps({"tool_name": tool_name, "tool_input": tool_input}),
        capture_output=True, text=True,
    )


def hook_bash(cmd: str) -> subprocess.CompletedProcess:
    return hook("Bash", {"command": cmd})


# --- what it refuses --------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "pip install pandas",
    "timeout 600 npm i puppeteer@23 --no-audit --no-fund 2>&1 | tail -5",
    "sudo apt-get install -y chromium",
    "dpkg --print-architecture; (apt-get install -y -q chromium | tail -3)",
    "curl -s https://api.github.com/repos/x",
    "wget https://example.com/data.csv",
    "git clone https://github.com/a/b",
    "python3 -c 'import urllib.request; urllib.request.urlopen(\"http://x\")'",
])
def test_egress_is_refused(cmd):
    r = hook_bash(cmd)
    assert r.returncode == 2, f"{cmd!r} was allowed:\n{r.stderr}"


@pytest.mark.parametrize("tool,payload", [
    ("WebFetch", {"url": "https://example.com/x"}),
    ("WebSearch", {"query": "norman general fund fye26"}),
])
def test_web_tools_are_refused(tool, payload):
    assert hook(tool, payload).returncode == 2


def test_the_refusal_says_what_to_use_instead():
    """The whole point. A silent block costs the same turns a timeout does."""
    r = hook_bash("pip install pandas")
    assert "BLOCKED" in r.stderr
    assert "MCP tools" in r.stderr
    assert "/workspace/data" in r.stderr
    # It must also say retrying is pointless, or the model tries the next
    # package manager -- one recorded run spent seven Bash calls doing exactly
    # that (npm, apt-get, chromium, puppeteer) before giving up.
    assert "will not work" in r.stderr


# --- what it must NOT refuse ------------------------------------------------
#
# A false positive here breaks a run that did nothing wrong, so these are as
# load-bearing as the cases above.

@pytest.mark.parametrize("cmd", [
    "curl -s http://light-servers:9142/mcp",          # sidecar health probe
    "curl -s http://localhost:8000/health",
    "curl -s http://127.0.0.1:9142/mcp",
    "pip install --no-index ./wheels/x.whl",          # pinned to disk
    "git status && git log --oneline -5",
    "grep -rn 'pip install' /workspace",
    "timeout 30 python3 /tmp/build.py",
    "(cd /workspace && python3 build.py)",
    "ls -la /workspace/data && cat /workspace/data/x.csv",
    "echo '<svg xmlns=\"http://www.w3.org/2000/svg\"/>' > /tmp/a.svg",
    "python3 - <<'PY'\nimport json\nprint(json.dumps({'a': 1}))\nPY",
])
def test_local_work_is_allowed(cmd):
    r = hook_bash(cmd)
    assert r.returncode == 0, f"{cmd!r} was refused:\n{r.stderr}"


def test_mcp_tools_are_never_egress():
    """The closed world is served over MCP; it is the answer, not the problem."""
    assert hook("mcp__LightGmail__list_messages", {"limit": 10}).returncode == 0
    assert hook("mcp__LightBudget__update_transaction", {"id": 1}).returncode == 0


# --- failure modes ----------------------------------------------------------

@pytest.mark.parametrize("payload", [
    "not json at all",
    "",
    "{}",
    '{"tool_name": "Bash"}',                 # no tool_input
    '{"tool_input": {"command": "ls"}}',     # no tool_name
])
def test_the_guard_fails_open(payload):
    """The router is the enforcement boundary; this layer buys turns.

    A hook that exits non-zero on a payload it did not expect would block every
    Bash call in the run, which is a far more expensive way to be wrong than
    letting one command through to a network that has no gateway anyway.
    """
    r = subprocess.run([sys.executable, str(RULES)], input=payload,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# --- the generated settings -------------------------------------------------

@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("guard") / "claude-settings.json"
    r = subprocess.run([sys.executable, str(MAKE_SETTINGS), str(RULES), str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(out.read_text())


def test_settings_declare_a_pretooluse_hook(settings):
    entries = settings["hooks"]["PreToolUse"]
    assert len(entries) == 1
    matcher = entries[0]["matcher"]
    for tool in ("Bash", "WebFetch", "WebSearch"):
        assert tool in matcher, matcher


def test_the_hook_command_carries_the_rules_and_runs(settings, tmp_path):
    """End-to-end: the command string as harbor ships it, run under /bin/sh.

    This is the test that would have caught the first draft, which piped the
    decoded script into `python3 -` and so consumed the hook's own stdin.
    """
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]

    denied = subprocess.run(
        ["/bin/sh", "-c", command],
        input=json.dumps({"tool_name": "Bash",
                          "tool_input": {"command": "pip install pandas"}}),
        capture_output=True, text=True,
    )
    assert denied.returncode == 2, denied.stderr
    assert "BLOCKED" in denied.stderr

    allowed = subprocess.run(
        ["/bin/sh", "-c", command],
        input=json.dumps({"tool_name": "Bash",
                          "tool_input": {"command": "ls /workspace/data"}}),
        capture_output=True, text=True,
    )
    assert allowed.returncode == 0, allowed.stderr


def test_the_settings_are_regenerated_from_the_live_rules(settings):
    """No cached copy: the shipped bytes must be today's rules.

    A stale settings.json would enforce whatever the rules were the last time
    somebody looked, which is the drift this whole arrangement exists to stop.
    """
    import base64
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    blob = command.split("'")[1]
    assert base64.b64decode(blob) == RULES.read_bytes()


# --- the parity that makes one rule set worth having ------------------------

PARITY_CASES = [
    "pip install pandas",
    "timeout 600 npm i puppeteer@23 | tail -5",
    "sudo -u root apt-get install -y chromium",
    "curl -s https://api.github.com/x",
    "git clone https://github.com/a/b",
    "(cd /tmp && pip install foo)",
    "curl -s http://light-servers:9142/mcp",
    "pip install --no-index ./wheels/x.whl",
    "grep -rn 'pip install' /workspace",
    "timeout 30 python3 /tmp/build.py",
    "ls /workspace/data",
]


@pytest.mark.parametrize("cmd", PARITY_CASES)
def test_hook_and_audit_agree(cmd, tmp_path):
    """The two callers of egress_rules must never disagree about a command.

    Disagreement in one direction is expensive and silent: the hook lets a
    command run, the model builds on it, and the audit discards the finished run
    hours later. This test is what keeps the two from drifting even though they
    execute in different processes, on different machines, at different times.
    """
    traj = tmp_path / "t.json"
    traj.write_text(json.dumps(
        {"steps": [{"tool": "Bash", "arguments": {"command": cmd}}]}))
    audit = subprocess.run([sys.executable, str(DETECT), str(traj)],
                           capture_output=True, text=True)

    hook_blocked = hook_bash(cmd).returncode == 2
    audit_blocked = audit.returncode == 2
    assert hook_blocked == audit_blocked, (
        f"{cmd!r}: hook {'blocked' if hook_blocked else 'allowed'} but audit "
        f"{'blocked' if audit_blocked else 'allowed'}"
    )
