"""judge_client.py: what tests/test.sh step 3 runs inside `main`.

A fake judge stands in for the judge container, so these check the client's
side of the contract -- what it writes, when it exits 0, and that it never
routes the call through main's egress proxy -- without docker or quota.
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import judge_client  # noqa: E402

VERDICTS = {"score": 1.0, "per_criterion": [{"number": "1", "satisfied": True, "justification": "x"}]}
GRADE_OK = {"ok": True, "reason": None, "returncode": 0, "breakdown": VERDICTS,
            "tokens": [{"model_name": "gpt-5.6-sol", "judge_output_tokens": 9}],
            "log_tail": "score=1.0", "graded_in": "judge-container",
            "model": "gpt-5.6-sol", "codex_version": "codex-cli 0.154.0"}


class FakeJudge:
    def __init__(self):
        self.health = []          # statuses to answer /healthz with, then 200
        self.grade = (200, GRADE_OK)
        self.requests = []


@pytest.fixture
def judge():
    fake = FakeJudge()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, doc):
            body = json.dumps(doc).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            code = fake.health.pop(0) if fake.health else 200
            self._send(code, {"status": "ok" if code == 200 else "unavailable",
                              "reason": None if code == 200 else "warming up"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            fake.requests.append({"token": self.headers.get("x-judge-token"), "body": body})
            self._send(*fake.grade)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fake.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield fake
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def run(tmp_path, monkeypatch, judge):
    monkeypatch.setattr(judge_client.time, "sleep", lambda s: None)
    monkeypatch.setenv("JUDGE_URL", judge.url)
    monkeypatch.setenv("JUDGE_TOKEN", "tok")
    monkeypatch.setenv("JUDGE_WAIT_SEC", "5")
    (tmp_path / "rubric.json").write_text(json.dumps({"criteria": [{"number": "1"}]}))
    (tmp_path / "traj.json").write_text(json.dumps({"steps": [], "final_message": "done"}))
    ver = tmp_path / "verifier"

    def go():
        rc = judge_client.main(["--rubric", str(tmp_path / "rubric.json"),
                                "--trajectory", str(tmp_path / "traj.json"),
                                "--output", str(ver / "rubric_breakdown.json"),
                                "--token-output", str(ver / "judge_tokens.json")])
        return rc, ver
    return go


def _marker(ver):
    return json.loads((ver / judge_client.MARKER_NAME).read_text())


def test_verdicts_are_written_beside_a_marker_and_the_usage(run, judge):
    rc, ver = run()
    assert rc == 0
    assert json.loads((ver / "rubric_breakdown.json").read_text()) == VERDICTS
    assert json.loads((ver / "judge_tokens.json").read_text())[0]["model_name"] == "gpt-5.6-sol"
    marker = _marker(ver)
    assert marker["ok"] is True and marker["graded_in"] == "judge-container"
    sent = judge.requests[0]
    assert sent["token"] == "tok"
    assert sent["body"]["trajectory"]["final_message"] == "done"


def test_a_failed_grade_leaves_no_breakdown_but_says_why(run, judge):
    judge.grade = (200, {**GRADE_OK, "ok": False, "reason": "grader returned no verdicts",
                         "breakdown": None})
    rc, ver = run()
    assert rc == 1
    assert not (ver / "rubric_breakdown.json").exists(), "a failed grade must read as UNSCORED, not zero"
    assert _marker(ver) == {**_marker(ver), "ok": False, "graded_in": None,
                            "reason": "grader returned no verdicts"}
    assert (ver / "judge_tokens.json").exists(), "quota was spent; the usage must still be recorded"


def test_no_token_means_no_call(run, judge, monkeypatch):
    monkeypatch.delenv("JUDGE_TOKEN")
    rc, ver = run()
    assert rc == 1 and not judge.requests
    assert "JUDGE_TOKEN" in _marker(ver)["reason"]


def test_a_refusal_surfaces_the_judges_reason(run, judge):
    judge.grade = (401, {"error": "bad or missing x-judge-token"})
    rc, ver = run()
    assert rc == 1
    assert "401" in _marker(ver)["reason"] and "x-judge-token" in _marker(ver)["reason"]


def test_it_waits_for_the_judge_to_become_healthy(run, judge):
    judge.health = [503, 503]
    rc, _ = run()
    assert rc == 0 and len(judge.requests) == 1


def test_an_unreachable_judge_is_reported_not_hung(run, monkeypatch):
    monkeypatch.setenv("JUDGE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("JUDGE_WAIT_SEC", "0")
    rc, ver = run()
    assert rc == 1
    assert "unreachable" in _marker(ver)["reason"]


def test_the_call_never_goes_through_mains_egress_proxy(run, monkeypatch):
    """Under isolation main's HTTP(S)_PROXY is squid, which would 403 the judge."""
    for var in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    rc, _ = run()
    assert rc == 0
