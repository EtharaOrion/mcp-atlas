"""The judge container: where the rubric is graded, and what it can see.

The rubric used to be graded on the host, where `codex exec --sandbox read-only`
can still READ every other run on disk -- measured: a canary file outside the
judge's working directory was cat'ed straight back. It is now graded in a
`judge` service of each bundle (tools/judge/codexbridge.py) that holds the codex
login and nothing else. These tests pin what makes that true, cheapest first:

  1. codexbridge in-process, against a fake grader: token, readiness, verdicts.
  2. every bundle: the judge service, its one mount, the token, test.sh step 3.
  3. the judge's own allowlist and the network shape overlay-judge.yaml builds.
  4. run_task.sh: builds the image, exports a fresh token, adds the overlay.
  5. the host fallback reuses container verdicts instead of re-buying them.
  6. docker, skipped without the image: the running judge mounts one file.
     JUDGE_LIVE=1 adds a real grade against gpt-5.6-sol (spends quota).
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
import yaml

from test_network_policy import OVERLAY, PROXY_DIR, _run_harbor_stage, fake_zbridge  # noqa: F401

REPO = Path(__file__).resolve().parents[2]
JUDGE_DIR = REPO / "tools" / "judge"
BRIDGE = JUDGE_DIR / "codexbridge.py"
OVERLAY_JUDGE = PROXY_DIR / "overlay-judge.yaml"
OVERLAY_ZBRIDGE = PROXY_DIR / "overlay-zbridge.yaml"
SQUID_JUDGE = PROXY_DIR / "squid-judge.conf"
RUN_TASK = REPO / "scripts" / "run_task.sh"
JUDGE_IMAGE = "codex-judge:latest"
AUTH_TARGET = "/run/codex-auth/auth.json"
BUNDLES = sorted(REPO.glob("tasks/*/task.toml"))

_opener = build_opener(ProxyHandler({}))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _call(url: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["x-judge-token"] = token
    req = Request(url, data=data, method="POST" if data is not None else "GET", headers=headers)
    try:
        with _opener.open(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


# =============================================================================
# 1. codexbridge, in-process
# =============================================================================

FAKE_GRADER = r'''
import argparse, json, os, pathlib, sys
ap = argparse.ArgumentParser()
for f in ("--rubric", "--trajectory", "--output", "--token-output", "--model"):
    ap.add_argument(f)
a = ap.parse_args()
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "fail":
    print("boom", file=sys.stderr)
    sys.exit(1)
rubric = json.loads(pathlib.Path(a.rubric).read_text())
traj = json.loads(pathlib.Path(a.trajectory).read_text())
rows = [] if mode == "empty" else [
    {"number": c["number"], "satisfied": True, "justification": traj["final_message"]}
    for c in rubric["criteria"]]
out = pathlib.Path(a.output)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"score": 1.0 if rows else 0.0, "per_criterion": rows}))
pathlib.Path(a.token_output).write_text(json.dumps([{"model_name": a.model}]))
print("graded", len(rows))
'''

RUBRIC = {"criteria": [{"number": "1", "criterion": "Refunds Kelso.", "is_positive": True}]}
TRAJ = {"steps": [{"tool": "refund", "arguments": {}, "response": "ok"}], "final_message": "refunded"}


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    mod = _load("codexbridge_under_test", BRIDGE)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    codex = bin_dir / "codex"
    codex.write_text("#!/bin/sh\necho 'codex-cli 0.0.0-test'\n")
    codex.chmod(0o755)
    grader = tmp_path / "fake_grader.py"
    grader.write_text(FAKE_GRADER)
    auth = tmp_path / "mounted-auth.json"
    auth.write_text('{"tokens": "host copy"}')

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("JUDGE_TOKEN", "s3cret")
    monkeypatch.setenv("JUDGE_CLI", str(grader))
    monkeypatch.setenv("CODEX_AUTH_SRC", str(auth))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    mod._state["credential_error"] = mod.install_credential()

    srv = mod.make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    class B:
        module = mod
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        home = tmp_path / "codex-home"
        mounted = auth
    yield B
    srv.shutdown()
    srv.server_close()


def test_health_is_ok_when_a_grade_could_run(bridge):
    status, doc = _call(f"{bridge.url}/healthz")
    assert status == 200, doc
    assert doc["status"] == "ok"


def test_health_names_a_missing_token(bridge, monkeypatch):
    monkeypatch.delenv("JUDGE_TOKEN")
    status, doc = _call(f"{bridge.url}/healthz")
    assert status == 503
    assert "JUDGE_TOKEN" in doc["reason"]


def test_health_names_a_missing_login(bridge, monkeypatch, tmp_path):
    """Compose's `up --wait` holds the trial on this, so a run with no login
    stops before the agent phase rather than after it."""
    monkeypatch.setenv("CODEX_AUTH_SRC", str(tmp_path / "nope.json"))
    bridge.module._state["credential_error"] = bridge.module.install_credential()
    status, doc = _call(f"{bridge.url}/healthz")
    assert status == 503
    assert "codex login not mounted" in doc["reason"]


@pytest.mark.parametrize("token", [None, "", "wrong"])
def test_grading_needs_the_run_token(bridge, token):
    """The agent shares a network with the judge. The token is what keeps it out."""
    status, doc = _call(f"{bridge.url}/grade", {"rubric": RUBRIC, "trajectory": TRAJ}, token)
    assert status == 401, doc


def test_a_grade_returns_the_verdicts_for_what_was_sent(bridge):
    status, doc = _call(f"{bridge.url}/grade", {"rubric": RUBRIC, "trajectory": TRAJ}, "s3cret")
    assert status == 200, doc
    assert doc["ok"] is True and doc["reason"] is None
    assert doc["graded_in"] == "judge-container"
    rows = doc["breakdown"]["per_criterion"]
    assert [r["number"] for r in rows] == ["1"]
    assert rows[0]["justification"] == "refunded", "the grader did not see the trajectory it was sent"
    assert doc["tokens"] == [{"model_name": "gpt-5.6-sol"}]


def test_no_verdicts_is_not_a_grade(bridge, monkeypatch):
    """rubric_judge_cli.py writes a zero breakdown with no criteria and exits 0
    when its backend preflight fails. Passing that on would publish "failed every
    criterion" for a run nobody graded."""
    monkeypatch.setenv("FAKE_MODE", "empty")
    status, doc = _call(f"{bridge.url}/grade", {"rubric": RUBRIC, "trajectory": TRAJ}, "s3cret")
    assert status == 200
    assert doc["ok"] is False and doc["breakdown"] is None
    assert doc["reason"] == "grader returned no verdicts"


def test_a_crashed_grader_is_reported_with_its_log(bridge, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "fail")
    status, doc = _call(f"{bridge.url}/grade", {"rubric": RUBRIC, "trajectory": TRAJ}, "s3cret")
    assert status == 200
    assert doc["ok"] is False and doc["reason"] == "grader exited 1"
    assert "boom" in doc["log_tail"]


def test_an_oversized_body_is_refused(bridge, monkeypatch):
    monkeypatch.setenv("JUDGE_MAX_BODY_BYTES", "64")
    status, _ = _call(f"{bridge.url}/grade", {"rubric": RUBRIC, "trajectory": TRAJ}, "s3cret")
    assert status == 413


def test_the_login_is_a_private_copy(bridge):
    """codex rewrites auth.json when it refreshes. It rewrites the copy."""
    copy = bridge.home / "auth.json"
    assert copy.read_text() == bridge.mounted.read_text()
    assert oct(copy.stat().st_mode & 0o777) == "0o600"
    copy.write_text("refreshed in the container")
    assert bridge.mounted.read_text() == '{"tokens": "host copy"}'


# =============================================================================
# 2. every bundle
# =============================================================================

pytest_bundles = pytest.mark.skipif(not BUNDLES, reason="no task bundles in this checkout")


def _ids(paths):
    return [p.parent.name[:40] for p in paths]


def _compose(task_toml: Path) -> dict:
    return yaml.safe_load((task_toml.parent / "environment" / "docker-compose.yaml").read_text())


@pytest_bundles
@pytest.mark.parametrize("task_toml", BUNDLES, ids=_ids(BUNDLES))
def test_bundle_declares_the_judge(task_toml):
    judge = (_compose(task_toml).get("services") or {}).get("judge")
    assert judge, "no judge service: the rubric would fall back to the host"
    assert judge.get("image") == JUDGE_IMAGE
    assert "build" not in judge, "the judge image is built once by run_task.sh, never per bundle"
    assert "${JUDGE_TOKEN" in str((judge.get("environment") or {}).get("JUDGE_TOKEN"))
    assert "--health" in " ".join((judge.get("healthcheck") or {}).get("test") or [])


@pytest_bundles
@pytest.mark.parametrize("task_toml", BUNDLES, ids=_ids(BUNDLES))
def test_the_judge_mounts_the_login_and_nothing_else(task_toml):
    """No task files, no output tree: the judge only sees the run it is sent."""
    vols = (_compose(task_toml)["services"]["judge"].get("volumes")) or []
    assert len(vols) == 1, vols
    source, target, mode = str(vols[0]).rsplit(":", 2)
    assert (target, mode) == (AUTH_TARGET, "ro"), vols
    assert "CODEX_AUTH_FILE" in source, vols


@pytest_bundles
@pytest.mark.parametrize("task_toml", BUNDLES, ids=_ids(BUNDLES))
def test_no_other_service_gets_the_login(task_toml):
    services = _compose(task_toml).get("services") or {}
    for name, spec in services.items():
        if name == "judge":
            continue
        text = json.dumps(spec)
        assert "CODEX_AUTH_FILE" not in text and "auth.json" not in text, (
            f"{name} can read the codex login")


@pytest_bundles
@pytest.mark.parametrize("task_toml", BUNDLES, ids=_ids(BUNDLES))
def test_the_verifier_receives_the_token_and_room_to_grade(task_toml):
    cfg = tomllib.loads(task_toml.read_text())
    assert cfg["verifier"]["env"].get("JUDGE_TOKEN") == "${JUDGE_TOKEN}"
    assert cfg["verifier"].get("timeout_sec", 0) >= 1800, (
        "the grade now happens inside the verifier window; judge_client gives up at 1200s")


@pytest_bundles
@pytest.mark.parametrize("task_toml", BUNDLES, ids=_ids(BUNDLES))
def test_step_3_asks_the_judge_and_3b_reports_it(task_toml):
    tests = task_toml.parent / "tests"
    sh = (tests / "test.sh").read_text()
    assert "/harness/scoring/judge_client.py" in sh
    assert "rubric_judge_cli.py" not in sh, "a judge in main would need the login where the agent ran"
    assert "/tests/test_judge_container.py" in sh
    assert (tests / "test_judge_container.py").is_file()


@pytest_bundles
@pytest.mark.parametrize("task_toml", BUNDLES, ids=_ids(BUNDLES))
def test_the_container_check_is_never_weighted(task_toml):
    """A judge outage is infrastructure. It must not move the agent's score, and
    harbor_to_output counts a failing unweighted test in test_outputs.py as
    'missed' -- which is why the check lives in a file of its own."""
    tests = task_toml.parent / "tests"
    names = {n.name for n in ast.walk(ast.parse((tests / "test_judge_container.py").read_text()))
             if isinstance(n, ast.FunctionDef)}
    weights = json.loads((tests / "test_weights.json").read_text())
    weighted = set(((weights.get("components") or {}).get("traj_tests") or {}).get("tests") or {})
    assert not names & weighted, sorted(names & weighted)
    assert "judge_container" not in (tests / "test_outputs.py").read_text()


@pytest_bundles
@pytest.mark.parametrize("task_toml", BUNDLES, ids=_ids(BUNDLES))
def test_reward_is_stamped_only_where_it_includes_the_rubric(task_toml):
    """producer=judge_container tells the host its work is done. A bundle whose
    own reward leaves the rubric out (bull-street's binary traj_pytest) must not
    claim it, or the published reward silently loses the rubric channel."""
    tests = task_toml.parent / "tests"
    stamped = "reward_producer.json" in (tests / "test.sh").read_text()
    reads_rubric = any("rubric_breakdown" in f.read_text()
                       for f in (tests / "test_outputs.py", tests / "grade.py") if f.is_file())
    assert stamped == reads_rubric, f"stamped={stamped} but reward reads rubric={reads_rubric}"


@pytest_bundles
@pytest.mark.parametrize("task_toml", BUNDLES, ids=_ids(BUNDLES))
def test_step_5_keeps_reward_json_numeric(task_toml):
    """harbor reads /logs/verifier/reward.json into VerifierResult.rewards,
    typed dict[str, float | int]. A string there fails the whole trial with a
    ValidationError and scores it 0 -- which is exactly what the first
    end-to-end run of the judge container did with a producer stamp. The label
    travels in reward_producer.json and run_task.sh adds it on the host."""
    sh = (task_toml.parent / "tests" / "test.sh").read_text()
    assert 'doc["producer"]' not in sh and 'out["producer"]' not in sh


# =============================================================================
# 3. the judge's allowlist and network
# =============================================================================

def _directives(path: Path) -> list[str]:
    return [l.split("#", 1)[0].strip() for l in path.read_text().splitlines()
            if l.split("#", 1)[0].strip()]


def test_the_judge_allowlist_is_what_codex_needs_and_no_more():
    """Measured behind an allow-all squid: chatgpt.com for the model,
    auth.openai.com for a login refresh. ab.chatgpt.com and oaiusercontent were
    also contacted, denied, and grading still succeeded."""
    hosts = set()
    for line in _directives(SQUID_JUDGE):
        m = re.match(r"acl\s+\S+\s+dstdomain\s+(.+)$", line)
        if m:
            hosts.update(m.group(1).split())
    assert hosts == {"chatgpt.com", "auth.openai.com"}, hosts


def test_the_judge_allowlist_is_tls_only_and_ends_in_deny():
    access = [l for l in _directives(SQUID_JUDGE) if l.startswith("http_access")]
    assert access[0] == "http_access deny CONNECT !SSL_ports"
    assert access[-1] == "http_access deny all"
    for rule in access[1:-1]:
        assert rule.startswith("http_access allow CONNECT SSL_ports judge_hosts"), rule


def test_both_squid_configs_are_baked_and_parsed_at_build():
    body = (PROXY_DIR / "Dockerfile").read_text()
    assert "COPY squid-judge.conf /etc/squid/squid-judge.conf" in body
    assert "squid -k parse -f /etc/squid/squid-judge.conf" in body


def test_the_agent_allowlist_is_untouched():
    hosts = set()
    for line in _directives(PROXY_DIR / "squid.conf"):
        m = re.match(r"acl\s+\S+\s+dstdomain\s+(.+)$", line)
        if m:
            hosts.update(m.group(1).split())
    assert hosts == {"api.anthropic.com"}


def _resolved(*files: Path, **extra_env) -> dict:
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin",
           "SCORING_DIR": str(REPO / "services" / "scoring"),
           "HOST_AGENT_LOGS_PATH": "/tmp/egress-out-test",
           "JUDGE_TOKEN": "compose-config-test",
           "CODEX_AUTH_FILE": "/tmp/codex-auth-test.json", **extra_env}
    args = ["docker", "compose"]
    for f in files:
        args += ["-f", str(f)]
    proc = subprocess.run(args + ["config", "--format", "json"], capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        pytest.fail(f"compose config failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


def _nets(cfg: dict, service: str) -> set[str]:
    return set(((cfg.get("services") or {}).get(service) or {}).get("networks") or {})


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
@pytest_bundles
@pytest.mark.parametrize("glm", [False, True], ids=["opus", "glm"])
def test_overlay_judge_gives_the_judge_its_own_way_out(glm, tmp_path):
    compose = BUNDLES[0].parent / "environment" / "docker-compose.yaml"
    files, env = [compose, OVERLAY], {}
    if glm:
        conf = tmp_path / "squid.conf"
        conf.write_text("")
        files.append(OVERLAY_ZBRIDGE)
        env["EGRESS_SQUID_CONF"] = str(conf)
    cfg = _resolved(*files, OVERLAY_JUDGE, **env)
    networks = cfg.get("networks") or {}
    assert (networks.get("judge-net") or {}).get("internal") is True
    assert _nets(cfg, "main") == {"default"}, "the agent must not reach the judge's proxy"
    assert _nets(cfg, "judge") == {"default", "judge-net"}, "the judge must not sit on egress"
    assert _nets(cfg, "judge-proxy") == {"judge-net", "egress"}
    assert _nets(cfg, "egress-proxy") == {"default", "egress"}
    on_egress = sorted(n for n in cfg["services"] if "egress" in _nets(cfg, n))
    assert on_egress == ["egress-proxy", "judge-proxy"], on_egress
    judge_env = cfg["services"]["judge"].get("environment") or {}
    assert judge_env.get("HTTPS_PROXY") == "http://judge-proxy:3128"
    assert "squid-judge.conf" in " ".join(cfg["services"]["judge-proxy"].get("command") or [])
    main_env = cfg["services"]["main"].get("environment") or {}
    assert main_env.get("HTTPS_PROXY") == "http://egress-proxy:3128"
    assert "judge" in main_env.get("NO_PROXY", "").split(",")


# =============================================================================
# 4. run_task.sh
# =============================================================================

JUDGE_BUNDLE_COMPOSE = """services:
  main:
    image: example/main:1
  judge:
    image: codex-judge:latest
"""


def test_run_task_knows_how_to_build_the_judge_image():
    body = RUN_TASK.read_text()
    m = re.search(r'^\s*codex-judge\)\s*echo\s+"([^"]+)"', body, re.M)
    assert m, "image_build_context has no codex-judge arm; ensure_image would try to pull it"
    ctx = Path(m.group(1).replace("$REPO", str(REPO)))
    assert (ctx / "Dockerfile").is_file()
    assert re.search(r'codex-judge\)\s*printf .*--build-context "scoring=\$REPO/services/scoring"', body), (
        "the judge Dockerfile COPYs --from=scoring; without the named context the build fails")


def test_makefile_builds_the_same_tag_with_the_same_context():
    body = (REPO / "Makefile").read_text()
    seg = body[body.index("build-codex-judge:"):]
    m = re.search(r"docker build --build-context scoring=(\S+) -t (\S+) (\S+)", seg)
    assert m, "build-codex-judge does not run docker build with the scoring context"
    assert (REPO / m.group(1)).resolve() == (REPO / "services" / "scoring").resolve()
    assert m.group(2) == JUDGE_IMAGE
    assert (REPO / m.group(3)).resolve() == JUDGE_DIR.resolve()


def _overlays(run) -> list[str]:
    return [run.argv[i + 1] for i, a in enumerate(run.argv) if a == "--extra-docker-compose"]


@pytest.fixture
def login(tmp_path):
    auth = tmp_path / "codex" / "auth.json"
    auth.parent.mkdir()
    auth.write_text("{}")
    return auth


def test_a_judge_bundle_gets_a_token_the_login_and_its_overlay(tmp_path, login):
    run = _run_harbor_stage(tmp_path / "r", compose=JUDGE_BUNDLE_COMPOSE,
                            CODEX_AUTH_FILE=str(login), JUDGE_TOKEN="from-the-caller")
    assert run.invoked, run.stderr[-2000:]
    token = run.env.get("JUDGE_TOKEN", "")
    assert re.fullmatch(r"[0-9a-f]{64}", token), token
    assert token != "from-the-caller", "a token that outlives the run is a token someone else has"
    assert Path(run.env["CODEX_AUTH_FILE"]).resolve() == login.resolve()
    assert _overlays(run) == [str(OVERLAY), str(OVERLAY_JUDGE)]


def test_every_invocation_gets_a_fresh_token(tmp_path, login):
    a = _run_harbor_stage(tmp_path / "a", compose=JUDGE_BUNDLE_COMPOSE, CODEX_AUTH_FILE=str(login))
    b = _run_harbor_stage(tmp_path / "b", compose=JUDGE_BUNDLE_COMPOSE, CODEX_AUTH_FILE=str(login))
    assert a.invoked and b.invoked
    assert a.env["JUDGE_TOKEN"] != b.env["JUDGE_TOKEN"]


def test_an_open_run_still_gets_a_token_but_no_judge_overlay(tmp_path, login):
    run = _run_harbor_stage(tmp_path, compose=JUDGE_BUNDLE_COMPOSE,
                            CODEX_AUTH_FILE=str(login), NETWORK_ISOLATION_OFF="1")
    assert run.invoked, run.stderr[-2000:]
    assert re.fullmatch(r"[0-9a-f]{64}", run.env.get("JUDGE_TOKEN", ""))
    assert _overlays(run) == []


def test_glm_runs_add_the_judge_overlay_after_zbridges(tmp_path, login, fake_zbridge):
    run = _run_harbor_stage(tmp_path, compose=JUDGE_BUNDLE_COMPOSE, CODEX_AUTH_FILE=str(login),
                            CC_MODE="zbridge", **fake_zbridge)
    assert run.invoked, run.stderr[-2000:]
    assert _overlays(run) == [str(OVERLAY), str(OVERLAY_ZBRIDGE), str(OVERLAY_JUDGE)]


def test_a_missing_login_stops_before_harbor(tmp_path):
    run = _run_harbor_stage(tmp_path, compose=JUDGE_BUNDLE_COMPOSE,
                            CODEX_AUTH_FILE=str(tmp_path / "missing.json"))
    assert not run.invoked
    assert run.returncode != 0


def test_a_bundle_without_a_judge_is_unchanged(tmp_path):
    run = _run_harbor_stage(tmp_path)
    assert run.invoked, run.stderr[-2000:]
    assert str(OVERLAY_JUDGE) not in run.argv


# =============================================================================
# 5. the host fallback
# =============================================================================

AGENT_STREAM = "\n".join(json.dumps(e) for e in [
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "LightStripe_create_refund", "input": {"charge": "ch_1"}}]}},
    {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": '{"status": "ok"}'}]}},
    {"type": "result", "result": "Refunded ch_1."},
]) + "\n"


@pytest.fixture
def graded_trial(tmp_path):
    """A trial whose judge container graded the rubric but whose bundle reward
    left it out -- the bull-street shape."""
    task = tmp_path / "tasks" / "demo"
    (task / "tests").mkdir(parents=True)
    (task / "tests" / "rubric.json").write_text(json.dumps(RUBRIC))
    (task / "tests" / "test_weights.json").write_text(json.dumps({"components": {
        "traj_tests": {"weight": 5, "graded": True}, "rubric": {"weight": 3, "graded": True}}}))
    trial = tmp_path / "job" / "demo__abc"
    (trial / "agent").mkdir(parents=True)
    (trial / "agent" / "claude-code.txt").write_text(AGENT_STREAM)
    v = trial / "verifier"
    v.mkdir()
    (v / "judge_container.json").write_text(json.dumps({"ok": True, "graded_in": "judge-container",
                                                        "model": "gpt-5.6-sol"}))
    (v / "rubric_breakdown.json").write_text(json.dumps({"score": 0.5, "per_criterion": [
        {"number": "1", "satisfied": True, "justification": "seen"}]}))
    (v / "reward_channel_a.json").write_text(json.dumps({"channel_a": 1.0, "guards_tripped": []}))
    (v / "state_channel.json").write_text(json.dumps({"available": False}))
    return trial, task


def test_the_host_reuses_container_verdicts_instead_of_rejudging(graded_trial, monkeypatch):
    hrp = _load("host_rubric_pass_under_test", REPO / "scripts" / "host_rubric_pass.py")
    trial, task = graded_trial

    def no_judge(*a, **k):
        raise AssertionError("the host called the judge for a rubric the container already graded")
    monkeypatch.setattr(hrp.subprocess, "run", no_judge)
    monkeypatch.setattr(sys, "argv", ["host_rubric_pass.py", "--trial", str(trial), "--task", str(task)])
    assert hrp.main() == 0
    doc = json.loads((trial / "verifier" / "reward_channel_a.json").read_text())
    assert doc["rubric_graded_on"] == "judge-container"
    assert doc["reward"] == hrp.norm_reward((5 * 1.0 + 3 * 0.5) / 8)
    assert json.loads((trial / "verifier" / "reward.json").read_text())["producer"] == "host_rubric_pass"


def test_rejudge_calls_the_judge_on_the_host_anyway(graded_trial, monkeypatch):
    hrp = _load("host_rubric_pass_rejudge", REPO / "scripts" / "host_rubric_pass.py")
    trial, task = graded_trial
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1)
    monkeypatch.setattr(hrp.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["host_rubric_pass.py", "--trial", str(trial),
                                      "--task", str(task), "--rejudge"])
    assert hrp.main() == 1
    assert calls and "rubric_judge_cli.py" in " ".join(map(str, calls[0]))


# =============================================================================
# 6. docker
# =============================================================================

def _image_present() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "image", "inspect", JUDGE_IMAGE],
                          capture_output=True).returncode == 0


needs_image = pytest.mark.skipif(not _image_present(),
                                 reason=f"{JUDGE_IMAGE} not built (make build-codex-judge)")


def _exec(name: str, *cmd: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "exec", name, *cmd], capture_output=True, text=True, **kw)


def _start_judge(auth: Path, token: str) -> str:
    name = f"judge-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--name", name, "-e", f"JUDGE_TOKEN={token}",
                    "-v", f"{auth}:{AUTH_TARGET}:ro", JUDGE_IMAGE],
                   check=True, capture_output=True)
    for _ in range(40):
        if _exec(name, "python3", "/judge/codexbridge.py", "--health").returncode == 0:
            return name
        time.sleep(0.5)
    logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    pytest.fail(f"judge never became healthy:\n{logs.stdout}{logs.stderr}")


@pytest.fixture
def running_judge(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text('{"fake": "login"}')
    canary = tmp_path / "canary.txt"
    canary.write_text("CANARY")
    name = _start_judge(auth, "t0ken")
    yield name, canary
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@needs_image
def test_the_running_judge_mounts_one_read_only_file(running_judge):
    name, _ = running_judge
    mounts = json.loads(subprocess.run(["docker", "inspect", name, "--format", "{{json .Mounts}}"],
                                       capture_output=True, text=True, check=True).stdout)
    assert [(m["Destination"], m["RW"]) for m in mounts] == [(AUTH_TARGET, False)], mounts


@needs_image
def test_host_files_are_not_visible_to_the_judge(running_judge):
    name, canary = running_judge
    assert _exec(name, "test", "-e", str(canary)).returncode != 0, "the judge can see a host file"
    assert _exec(name, "sh", "-c", f"echo x >> {AUTH_TARGET}").returncode != 0, "the login mount is writable"
    mode = _exec(name, "sh", "-c", 'stat -c %a "$CODEX_HOME/auth.json"')
    assert mode.stdout.strip() == "600", mode


@needs_image
def test_the_running_judge_refuses_a_grade_without_the_token(running_judge):
    name, _ = running_judge
    probe = ("import urllib.request as u\n"
             "r=u.Request('http://127.0.0.1:8770/grade',data=b'{}',method='POST',"
             "headers={'Content-Type':'application/json'})\n"
             "try:\n    u.build_opener(u.ProxyHandler({})).open(r); print(200)\n"
             "except Exception as e:\n    print(getattr(e,'code',e))\n")
    out = _exec(name, "python3", "-c", probe)
    assert out.stdout.strip() == "401", out


@needs_image
@pytest.mark.skipif(os.environ.get("JUDGE_LIVE") != "1", reason="set JUDGE_LIVE=1 to spend quota on a real grade")
def test_live_grade_through_the_container(tmp_path):
    auth = Path(os.environ.get("CODEX_AUTH_FILE", Path.home() / ".codex" / "auth.json"))
    if not auth.is_file():
        pytest.skip("no codex login on this machine")
    name = _start_judge(auth, "live-token")
    try:
        for src, dst in ((REPO / "services" / "scoring" / "judge_client.py", "/tmp/judge_client.py"),):
            subprocess.run(["docker", "cp", str(src), f"{name}:{dst}"], check=True)
        (tmp_path / "r.json").write_text(json.dumps({"criteria": [
            {"number": "1", "criterion": "The agent refunds charge ch_1.", "evaluation_target": "trajectory",
             "is_positive": True, "importance": "critically_important", "score": 5, "weight": 5}]}))
        (tmp_path / "t.json").write_text(json.dumps(TRAJ))
        subprocess.run(["docker", "cp", str(tmp_path / "r.json"), f"{name}:/tmp/r.json"], check=True)
        subprocess.run(["docker", "cp", str(tmp_path / "t.json"), f"{name}:/tmp/t.json"], check=True)
        out = subprocess.run(["docker", "exec", "-e", "JUDGE_URL=http://127.0.0.1:8770",
                              "-e", "JUDGE_TOKEN=live-token", name, "python3", "/tmp/judge_client.py",
                              "--rubric", "/tmp/r.json", "--trajectory", "/tmp/t.json",
                              "--output", "/tmp/out/rubric_breakdown.json",
                              "--token-output", "/tmp/out/judge_tokens.json"],
                             capture_output=True, text=True, timeout=900)
        assert out.returncode == 0, out.stdout + out.stderr
        marker = json.loads(_exec(name, "cat", "/tmp/out/judge_container.json").stdout)
        assert marker["ok"] is True and marker["model"] == "gpt-5.6-sol"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
