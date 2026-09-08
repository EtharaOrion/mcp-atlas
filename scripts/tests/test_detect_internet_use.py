"""tools/network/detect_internet_use.py -- the closed-world guarantee.

Two things must hold, and the second is the one that costs real money if it
breaks: every form of egress is caught, and NO legitimate bundle traffic is
flagged. A false positive here blocks a run that did nothing wrong, so the
sidecar/offline cases below are as load-bearing as the detection cases.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
DETECT = REPO / "tools" / "network" / "detect_internet_use.py"


def run(steps, *flags, tmp_path):
    traj = tmp_path / "t.json"
    traj.write_text(json.dumps({"steps": steps}))
    return subprocess.run(
        [sys.executable, str(DETECT), str(traj), *flags],
        capture_output=True, text=True,
    )


def bash(cmd):
    return {"tool": "Bash", "arguments": {"command": cmd}}


# --- caught -----------------------------------------------------------------

@pytest.mark.parametrize("step", [
    {"tool": "WebSearch", "arguments": {"query": "cherry side table price"}},
    {"tool": "WebFetch", "arguments": {"url": "https://example.com/x"}},
    bash("curl -s https://api.github.com/repos/x"),
    bash("wget https://example.com/data.csv"),
    bash("pip install pandas"),
    bash("npm install left-pad"),
    bash("apt-get install -y jq"),
    bash("git clone https://github.com/a/b"),
    bash("python3 -c \"import urllib.request; urllib.request.urlopen('http://x.com')\""),
    bash("ssh user@example.com ls"),
    bash("ls /workspace && curl https://evil.test/x"),
])
def test_egress_is_blocked(step, tmp_path):
    r = run([step], tmp_path=tmp_path)
    assert r.returncode == 2, r.stdout


# --- not caught -------------------------------------------------------------

@pytest.mark.parametrize("step", [
    # The sidecars are the point of the bundle, not egress.
    bash("curl -s http://light-servers:9142/mcp"),
    bash("curl -s http://localhost:9110/mcp"),
    bash("curl -s http://127.0.0.1:9067/mcp"),
    # Ordinary local work, including the docx/zip unpacking these tasks do.
    bash("ls -la /workspace/data"),
    bash("unzip -o -q /workspace/data/policy.docx -d /tmp/x"),
    bash("git status"),
    bash("git log --oneline -5"),
    bash("pip install --no-index ./wheels/x.whl"),
    bash("python3 -c \"import json; print(json.load(open('/tmp/a.json')))\""),
    {"tool": "mcp__LightEtsy__update_listing", "arguments": {"listing_id": 1020}},
    {"tool": "Read", "arguments": {"file_path": "/workspace/data/img_20.jpg"}},
])
def test_local_work_is_not_flagged(step, tmp_path):
    r = run([step], tmp_path=tmp_path)
    assert r.returncode == 0, r.stdout


def test_clean_run_passes(tmp_path):
    steps = [bash("ls /workspace/data"),
             {"tool": "mcp__LightGmail__list_messages", "arguments": {}}]
    r = run(steps, tmp_path=tmp_path)
    assert r.returncode == 0
    assert "no internet access" in r.stdout


# --- shapes, flags, edges ---------------------------------------------------

def test_raw_harbor_trajectory_shape_is_understood(tmp_path):
    """Harbor publishes tool_calls[].function_name; tests/test.sh writes tool/arguments.

    Both must audit identically or the check silently covers only one of the two
    places a trajectory is read from.
    """
    steps = [{"tool_calls": [
        {"function_name": "Bash", "arguments": {"command": "curl https://evil.test"}}]}]
    r = run(steps, tmp_path=tmp_path)
    assert r.returncode == 2, r.stdout


def test_warn_only_reports_without_blocking(tmp_path):
    r = run([bash("curl https://evil.test")], "--warn-only", tmp_path=tmp_path)
    assert r.returncode == 0
    assert "FAIL" in r.stdout


def test_findings_are_written_for_grading(tmp_path):
    out = tmp_path / "audit.json"
    run([bash("curl https://evil.test")], "--json", str(out), tmp_path=tmp_path)
    data = json.loads(out.read_text())
    assert data["used_internet"] is True
    assert data["findings"] and data["findings"][0]["kind"] == "fetch"


def test_clean_run_records_a_negative_result(tmp_path):
    out = tmp_path / "audit.json"
    run([bash("ls /workspace")], "--json", str(out), tmp_path=tmp_path)
    assert json.loads(out.read_text())["used_internet"] is False


def test_one_command_yields_one_finding(tmp_path):
    """`curl <url>` trips both the URL sweep and the token walk; the report
    should name the act once, not name every rule that matched it."""
    out = tmp_path / "audit.json"
    run([bash("curl https://evil.test/x")], "--json", str(out), tmp_path=tmp_path)
    kinds = [f["kind"] for f in json.loads(out.read_text())["findings"]]
    assert kinds == ["fetch"]


def test_unlexable_command_is_reported_not_skipped(tmp_path):
    """An unbalanced quote must not become a silent pass -- that is the one
    hole worth having none of."""
    r = run([bash('curl "https://evil.test')], tmp_path=tmp_path)
    assert r.returncode == 2, r.stdout


def test_missing_trajectory_does_not_block(tmp_path):
    """A run that produced nothing is the aborted-trial guard's business, not
    this one's; blocking here would double-report it under the wrong name."""
    r = subprocess.run(
        [sys.executable, str(DETECT), str(tmp_path / "nope.json")],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert "warn" in r.stdout


def test_unparseable_trajectory_blocks(tmp_path):
    bad = tmp_path / "t.json"
    bad.write_text("{not json")
    r = subprocess.run([sys.executable, str(DETECT), str(bad)],
                       capture_output=True, text=True)
    assert r.returncode == 2


# --- the proxy log against the run's allowlist --------------------------------

BEDROCK_HOST = "bedrock-runtime.ap-south-1.amazonaws.com"


def squid_line(host, code="TCP_TUNNEL/200"):
    """One squid-native access.log line: ts elapsed client CODE/STATUS bytes METHOD URL ..."""
    return f"1700000000.000 120 172.18.0.3 {code} 5000 CONNECT {host}:443 - HIER_DIRECT/1.2.3.4 -\n"


def test_allowed_line_to_an_unlisted_host_is_a_breach_by_default(tmp_path):
    """The default allowlist is api.anthropic.com. A Bedrock run audited
    without --allowed-host must therefore FAIL, not pass quietly -- an older
    tree must never certify a run whose policy it did not know."""
    log = tmp_path / "egress-access.log"
    log.write_text(squid_line(BEDROCK_HOST))
    r = run([], "--access-log", str(log), tmp_path=tmp_path)
    assert r.returncode == 2
    assert "allowlist-breach" in r.stdout


def test_allowed_host_flag_is_the_run_allowlist(tmp_path):
    """run_task.sh passes the allowlist it recorded at harbor time; under
    CC_MODE=bedrock that is the regional runtime and the log is clean."""
    log = tmp_path / "egress-access.log"
    log.write_text(squid_line(BEDROCK_HOST))
    r = run([], "--access-log", str(log), "--allowed-host", BEDROCK_HOST, tmp_path=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "allowlist-breach" not in r.stdout


def test_allowed_host_flag_replaces_the_default_rather_than_adding_to_it(tmp_path):
    """One host per run. A Bedrock run that reached api.anthropic.com left
    the policy it was run under, and the audit must say so."""
    log = tmp_path / "egress-access.log"
    log.write_text(squid_line("api.anthropic.com"))
    r = run([], "--access-log", str(log), "--allowed-host", BEDROCK_HOST, tmp_path=tmp_path)
    assert r.returncode == 2
    assert "allowlist-breach" in r.stdout


def test_denials_are_still_findings_under_a_custom_allowlist(tmp_path):
    log = tmp_path / "egress-access.log"
    log.write_text(squid_line(BEDROCK_HOST) + squid_line("example.com", "TCP_DENIED/403"))
    r = run([], "--access-log", str(log), "--allowed-host", BEDROCK_HOST, tmp_path=tmp_path)
    assert r.returncode == 2
    assert "proxy-denied" in r.stdout
