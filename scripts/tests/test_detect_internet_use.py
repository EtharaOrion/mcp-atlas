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


HEREDOC_EDIT = """python3 - << 'PYEOF'
s = open('/tmp/page.py', encoding='utf-8').read()
s = s.replace(\"\"\" --neutral:#383835;\"\"\", \"\"\" --neutral:#898781;\"\"\")
# tooltips: the value leads, the label follows
open('/tmp/page.py', 'w', encoding='utf-8').write(s)
PYEOF
python3 /tmp/page.py"""


def test_a_heredoc_of_local_python_is_not_a_finding(tmp_path):
    """shlex has no heredoc rule, so it lexed the body as shell words and the
    first apostrophe in it raised "No closing quotation" -- and the fail-closed
    branch turned that parser limit into a blocked run. `python3 - <<'PY'` is
    how the agent writes most of its multi-line edits; this one only touches
    /tmp."""
    r = run([bash(HEREDOC_EDIT)], tmp_path=tmp_path)
    assert r.returncode == 0, r.stdout


def test_lifting_the_body_out_does_not_blind_the_lexer(tmp_path):
    """Only the body is lifted. Commands after the terminator still get walked,
    or the heredoc becomes a place to hide the next line."""
    r = run([bash(HEREDOC_EDIT.replace("python3 /tmp/page.py",
                                       "curl https://evil.test/x"))],
            tmp_path=tmp_path)
    assert r.returncode == 2, r.stdout


@pytest.mark.parametrize("body", [
    "curl https://evil.test/x",             # also caught by the raw URL sweep
    "curl evil.test/x",                     # no scheme: only the verb walk sees it
    "pip install pandas",                   # no host at all: flags read it
    "git clone https://github.com/a/b",
    "import urllib.request as u; u.urlopen('x')",
])
def test_egress_inside_a_heredoc_is_still_caught(body, tmp_path):
    """A body lifted out for lexing is audited, not excused -- otherwise the
    heredoc becomes the place to keep an install where nothing looks."""
    r = run([bash(f"bash << 'EOF'\n{body}\nEOF")], tmp_path=tmp_path)
    assert r.returncode == 2, r.stdout


def test_every_line_of_a_heredoc_body_is_walked(tmp_path):
    """shlex does not treat a newline as a separator, so a body lexed whole
    collapses into one run-on segment and only its first word is ever read as a
    verb. The install on line two has to be found too."""
    r = run([bash("bash << 'EOF'\nls /workspace\npip install pandas\nEOF")],
            tmp_path=tmp_path)
    assert r.returncode == 2, r.stdout


def test_prose_written_through_a_heredoc_is_not_egress(tmp_path):
    """The walk reads verbs, not words. A note that mentions curl is not a run
    of curl -- and writing notes to /workspace is the job."""
    r = run([bash("cat > /workspace/NOTES.md << 'EOF'\n"
                  "The data was not fetched with curl -- it ships in the bundle.\n"
                  "EOF")], tmp_path=tmp_path)
    assert r.returncode == 0, r.stdout


def test_a_heredoc_fetch_is_named_once(tmp_path):
    """The body walk and the raw URL sweep both see the same act. _collapse
    keys on (step, evidence), so the body's findings must carry the whole
    command as evidence, exactly as the command-line walk does."""
    out = tmp_path / "audit.json"
    run([bash("bash << 'EOF'\ncurl https://evil.test/x\nEOF")],
        "--json", str(out), tmp_path=tmp_path)
    kinds = [f["kind"] for f in json.loads(out.read_text())["findings"]]
    assert kinds == ["fetch"], kinds


def test_an_unterminated_heredoc_is_still_audited(tmp_path):
    """A body that never meets its delimiter runs to the end of the command.
    Nothing may fall off that edge unread."""
    r = run([bash("bash << 'EOF'\npip install pandas")], tmp_path=tmp_path)
    assert r.returncode == 2, r.stdout


def test_missing_trajectory_does_not_block(tmp_path):
    """A run that produced nothing is the aborted-trial guard's business, not
    this one's; blocking here would double-report it under the wrong name."""
    r = subprocess.run(
        [sys.executable, str(DETECT), str(tmp_path / "nope.json")],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert "warn" in r.stdout


# --- install attempt vs install that landed ---------------------------------
#
# The command line says the model reached for an index; the response says
# whether it got there. Both block, but only the second is a breach, and the
# response is the only witness that survives a run with no proxy log.

def bash_out(cmd, out):
    return {"tool": "Bash", "arguments": {"command": cmd}, "response": out}


PIP_DENIED = (
    "WARNING: Retrying (Retry(total=4)) after connection broken by "
    "'ProxyError('Cannot connect to proxy.', ...)': /simple/pandas/\n"
    "ERROR: Could not find a version that satisfies the requirement pandas"
)
PIP_LANDED = (
    "Collecting pandas\n  Downloading pandas-2.2.3-cp312-manylinux.whl (12 MB)\n"
    "Installing collected packages: pandas\n"
    "Successfully installed pandas-2.2.3"
)


@pytest.mark.parametrize("out", [
    PIP_LANDED,
    "added 1 package in 812ms",                                    # npm
    "Get:1 http://deb.debian.org/debian bookworm/main jq amd64 1.6\n"
    "Setting up jq (1.6-2.1) ...",                                 # apt
    "Installed 3 packages in 41ms\n + pandas==2.2.3",              # uv
    "(1/2) Installing jq (1.7.1-r0)",                              # apk
])
def test_successful_install_is_a_breach(out, tmp_path):
    audit = tmp_path / "audit.json"
    r = run([bash_out("pip install pandas", out)], "--json", str(audit),
            tmp_path=tmp_path)
    assert r.returncode == 2, r.stdout
    data = json.loads(audit.read_text())
    assert [f["kind"] for f in data["findings"]] == ["package-installed"]
    assert data["outcome"] == "breach", data


def test_denied_install_is_an_attempt_not_a_breach(tmp_path):
    """The proxy refusing pip is the block WORKING. It still blocks the run --
    reaching for an index is disqualifying here -- but calling it a breach
    sends an operator hunting a leak that never happened."""
    audit = tmp_path / "audit.json"
    r = run([bash_out("pip install pandas", PIP_DENIED)], "--json", str(audit),
            tmp_path=tmp_path)
    assert r.returncode == 2, r.stdout
    data = json.loads(audit.read_text())
    assert [f["kind"] for f in data["findings"]] == ["package-install"]
    assert data["outcome"] == "unverified", data


@pytest.mark.parametrize("out", [
    "Requirement already satisfied: pandas in /usr/lib/python3/dist-packages",
    "up to date, audited 1 package in 190ms",
    "jq is already the newest version (1.6-2.1).\n"
    "0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.",
])
def test_already_on_disk_is_not_a_breach(out, tmp_path):
    """A warm cache reaches no index. Reading these as success would turn the
    most ordinary install output there is into a false breach."""
    audit = tmp_path / "audit.json"
    run([bash_out("pip install pandas", out)], "--json", str(audit),
        tmp_path=tmp_path)
    data = json.loads(audit.read_text())
    assert [f["kind"] for f in data["findings"]] == ["package-install"]
    assert data["outcome"] != "breach", data


def test_offline_install_stays_clean_whatever_it_prints(tmp_path):
    """`pip install --no-index ./x.whl` prints "Successfully installed" too. It
    is pinned to disk, so the success marker must not resurrect it."""
    r = run([bash_out("pip install --no-index ./wheels/x.whl",
                      "Successfully installed x-1.0.0")], tmp_path=tmp_path)
    assert r.returncode == 0, r.stdout


def test_missing_response_falls_back_to_the_attempt(tmp_path):
    """A truncated trajectory is not evidence the install failed, so absence
    must read as the weaker claim, not the stronger one."""
    audit = tmp_path / "audit.json"
    run([bash("pip install pandas")], "--json", str(audit), tmp_path=tmp_path)
    assert [f["kind"] for f in json.loads(audit.read_text())["findings"]] \
        == ["package-install"]


def test_harbor_shape_carries_the_response_too(tmp_path):
    """Harbor keeps the result in observation.results, joined to the call by id.
    Miss that and the stronger finding only ever fires on verifier-shape
    trajectories -- half the places this scanner runs."""
    steps = [{"tool_calls": [{"tool_call_id": "t1", "function_name": "Bash",
                              "arguments": {"command": "pip install pandas"}}],
              "observation": {"results": [{"source_call_id": "t1",
                                           "content": PIP_LANDED}]}}]
    audit = tmp_path / "audit.json"
    r = run(steps, "--json", str(audit), tmp_path=tmp_path)
    assert r.returncode == 2, r.stdout
    assert json.loads(audit.read_text())["outcome"] == "breach"


def test_harbor_results_are_matched_by_id_not_position(tmp_path):
    """One step, two calls, results in the other order: a positional zip would
    hang the install output on the `ls` and clear the real one."""
    steps = [{"tool_calls": [
        {"tool_call_id": "t1", "function_name": "Bash",
         "arguments": {"command": "ls /workspace"}},
        {"tool_call_id": "t2", "function_name": "Bash",
         "arguments": {"command": "pip install pandas"}}],
        "observation": {"results": [{"source_call_id": "t2", "content": PIP_LANDED},
                                    {"source_call_id": "t1", "content": "data"}]}}]
    audit = tmp_path / "audit.json"
    run(steps, "--json", str(audit), tmp_path=tmp_path)
    assert json.loads(audit.read_text())["outcome"] == "breach"


# --- namespace URIs are identifiers, not addresses --------------------------

@pytest.mark.parametrize("cmd", [
    # The exact command that blocked a clean run: the agent CHECKING its own
    # output had no external references.
    "python3 -c \"print('ok', 'http://' not in html.replace('http://www.w3.org/2000/svg',''))\"",
    'echo \'<svg xmlns="http://www.w3.org/2000/svg"></svg>\' > /workspace/out/chart.svg',
    'echo \'<html xmlns="http://www.w3.org/1999/xhtml">\' > /tmp/p.html',
    # .docx internals, which every bundle that unpacks an attachment will see.
    "grep -o 'http://schemas.openxmlformats.org/[a-z/]*' /tmp/x/word/document.xml",
])
def test_xml_namespaces_are_not_egress(cmd, tmp_path):
    """xmlns URLs are never dereferenced. Flagging them blocks a run that did
    nothing wrong, which is the expensive direction to be wrong in."""
    r = run([bash(cmd)], tmp_path=tmp_path)
    assert r.returncode == 0, r.stdout


def test_fetching_a_namespace_host_is_still_egress(tmp_path):
    """The exemption is for the string sweep only. A verb aimed at the host is
    a real request whatever the host is famous for."""
    r = run([bash("curl -s http://www.w3.org/2000/svg > /tmp/x")], tmp_path=tmp_path)
    assert r.returncode == 2, r.stdout


# --- outcome vocabulary -----------------------------------------------------

def test_a_run_with_no_findings_is_clean_not_unverified(tmp_path):
    """run_task.sh ranks this field across runs to word its banner. A run with
    nothing to report must not arrive there wearing a word that means the model
    reached for something."""
    out = tmp_path / "audit.json"
    run([bash("ls /workspace/data")], "--json", str(out), tmp_path=tmp_path)
    assert json.loads(out.read_text())["outcome"] == "clean"


def test_proxy_findings_without_a_trajectory_are_setup_not_the_model(tmp_path):
    """An aborted trial leaves a proxy log and no trajectory. The requests in it
    were made by harbor's setup before the agent ran, so naming the model sends
    an operator to a transcript that does not exist."""
    alog = tmp_path / "egress-access.log"
    alog.write_text(
        "1788890425.161 0 192.168.158.4 TCP_DENIED/403 3490 GET "
        "http://deb.debian.org/debian/dists/trixie/InRelease - HIER_NONE/- text/html\n")
    out = tmp_path / "audit.json"
    r = subprocess.run(
        [sys.executable, str(DETECT), str(tmp_path / "absent.json"),
         "--access-log", str(alog), "--json", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 2, r.stdout
    data = json.loads(out.read_text())
    assert data["outcome"] == "setup", data
    assert data["tool_calls"] == 0


def test_unverified_still_means_unverified_with_a_trajectory(tmp_path):
    """The new words must not swallow the old one: a real tool call with no
    proxy log is still the claim we cannot make."""
    out = tmp_path / "audit.json"
    run([bash("curl https://evil.test")], "--json", str(out), tmp_path=tmp_path)
    assert json.loads(out.read_text())["outcome"] == "unverified"


def test_unparseable_trajectory_blocks(tmp_path):
    bad = tmp_path / "t.json"
    bad.write_text("{not json")
    r = subprocess.run([sys.executable, str(DETECT), str(bad)],
                       capture_output=True, text=True)
    assert r.returncode == 2
