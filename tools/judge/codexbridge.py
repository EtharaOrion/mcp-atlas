#!/usr/bin/env python3
"""codexbridge: the rubric judge, inside its own container.

The rubric used to be graded on the host, where `codex exec --sandbox read-only`
can still READ the whole disk -- other runs under output/, answer files under
tasks/*/tests -- because read-only only forbids writes. This service runs the
same grader (rubric_judge_cli.py, baked into the image) in a container that
holds nothing but itself and one credential, so "the judge cannot see other
runs" is a property of what is mounted, not of what the model chooses to do.

  GET  /healthz   200 when a grade could run: token set, codex login installed,
                  codex and the grader present. Compose's healthcheck calls it
                  (`codexbridge.py --health`) and harbor's `up --wait` holds the
                  trial on it, so a missing credential fails before the agent
                  phase instead of after it.
  POST /grade     {"rubric": {...}, "trajectory": {...}} + header x-judge-token.
                  Runs the grader and returns what it wrote.

The token is made per run by scripts/run_task.sh and reaches two places only:
this container's environment and the verifier step's (task.toml [verifier.env];
harbor applies that to the test script, never to the agent). The agent shares a
network with this service but never holds the token.

The login arrives as a read-only mount and is COPIED into CODEX_HOME at start.
codex refreshes its access token by rewriting auth.json; the copy is what it
rewrites, so nothing in here can change the host's file.

Stdlib only.
"""
from __future__ import annotations

import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

HERE = Path(__file__).resolve().parent
GRADED_IN = "judge-container"
LOG_TAIL_CHARS = 4000

_state: dict[str, str | None] = {"credential_error": "codex login not installed yet"}
_grade_lock = threading.Lock()
_codex_version: str | None = None


def _port() -> int:
    return int(os.environ.get("JUDGE_PORT", "8770"))


def _model() -> str:
    return os.environ.get("JUDGE_MODEL", "gpt-5.6-sol")


def _judge_cli() -> Path:
    return Path(os.environ.get("JUDGE_CLI", HERE / "rubric_judge_cli.py"))


def _max_body() -> int:
    return int(os.environ.get("JUDGE_MAX_BODY_BYTES", str(64 * 1024 * 1024)))


def _grade_timeout() -> float:
    return float(os.environ.get("JUDGE_GRADE_TIMEOUT_SEC", "1500"))


def install_credential() -> str | None:
    """Copy the mounted login into CODEX_HOME. None on success, else the reason."""
    src = Path(os.environ.get("CODEX_AUTH_SRC", "/run/codex-auth/auth.json"))
    if not src.is_file() or src.stat().st_size == 0:
        return f"codex login not mounted at {src} (scripts/run_task.sh sets CODEX_AUTH_FILE)"
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        home.mkdir(parents=True, exist_ok=True)
        dest = home / "auth.json"
        shutil.copyfile(src, dest)
        dest.chmod(0o600)
    except OSError as exc:
        return f"could not install codex login into {home}: {exc}"
    return None


def not_ready() -> str | None:
    """Why a grade cannot run right now, or None."""
    if not os.environ.get("JUDGE_TOKEN"):
        return "JUDGE_TOKEN is not set (scripts/run_task.sh creates one per run)"
    if _state["credential_error"]:
        return _state["credential_error"]
    if not shutil.which("codex"):
        return "codex CLI not found on PATH"
    if not _judge_cli().is_file():
        return f"grader missing at {_judge_cli()}"
    return None


def codex_version() -> str | None:
    global _codex_version
    if _codex_version is None:
        try:
            out = subprocess.run(["codex", "--version"], capture_output=True,
                                 text=True, timeout=30)
            _codex_version = (out.stdout or out.stderr).strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            _codex_version = "unknown"
    return _codex_version


def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def grade(rubric: dict, trajectory: dict) -> dict:
    """Run the grader once over one run's rubric and trajectory.

    `ok` means real verdicts came back. rubric_judge_cli.py writes a zero-score
    breakdown with no criteria when its backend preflight fails, and exits 0;
    passing that on would publish "failed every criterion" for a run nobody
    graded, so an empty verdict list is a failure here.
    """
    with tempfile.TemporaryDirectory(prefix="grade-") as tmp:
        work = Path(tmp)
        out_dir = work / "out"
        (work / "rubric.json").write_text(json.dumps(rubric))
        (work / "trajectory.json").write_text(json.dumps(trajectory))
        breakdown_path = out_dir / "rubric_breakdown.json"
        tokens_path = out_dir / "judge_tokens.json"
        cmd = [sys.executable, str(_judge_cli()),
               "--rubric", str(work / "rubric.json"),
               "--trajectory", str(work / "trajectory.json"),
               "--output", str(breakdown_path),
               "--token-output", str(tokens_path),
               "--model", _model()]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=_grade_timeout(), cwd=tmp)
            rc, log = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            rc, log = None, f"grader timed out after {_grade_timeout():.0f}s"

        breakdown = _load_json(breakdown_path)
        usage = _load_json(tokens_path)
        failed_marker = out_dir / "rubric_judge_failed.txt"
        failed = failed_marker.read_text() if failed_marker.is_file() else None
        rows = (breakdown or {}).get("per_criterion") or (breakdown or {}).get("results") or []

        reason = None
        if rc != 0:
            reason = f"grader exited {rc}" if rc is not None else "grader timed out"
        elif failed:
            reason = failed.strip().splitlines()[0] if failed.strip() else "grader wrote a failure marker"
        elif not rows:
            reason = "grader returned no verdicts"
        return {
            "ok": reason is None,
            "reason": reason,
            "returncode": rc,
            "breakdown": breakdown if reason is None else None,
            "tokens": usage,
            "log_tail": log[-LOG_TAIL_CHARS:],
            "graded_in": GRADED_IN,
            "model": _model(),
            "codex_version": codex_version(),
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "codexbridge"

    def log_message(self, fmt, *args):
        sys.stderr.write("[codexbridge] " + (fmt % args) + "\n")

    def _send(self, code: int, doc: dict) -> None:
        body = json.dumps(doc).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/healthz":
            return self._send(404, {"error": "not found"})
        why = not_ready()
        self._send(503 if why else 200,
                   {"status": "unavailable" if why else "ok", "reason": why,
                    "model": _model()})

    def do_POST(self):
        if self.path != "/grade":
            return self._send(404, {"error": "not found"})
        why = not_ready()
        if why:
            return self._send(503, {"error": why})
        sent = self.headers.get("x-judge-token", "").encode()
        if not hmac.compare_digest(sent, os.environ["JUDGE_TOKEN"].encode()):
            return self._send(401, {"error": "bad or missing x-judge-token"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return self._send(411, {"error": "Content-Length required"})
        if length > _max_body():
            self.close_connection = True
            return self._send(413, {"error": f"body {length} bytes exceeds {_max_body()}"})
        try:
            req = json.loads(self.rfile.read(length))
            rubric, trajectory = req["rubric"], req["trajectory"]
            if not isinstance(rubric, dict) or not isinstance(trajectory, dict):
                raise TypeError("rubric and trajectory must be JSON objects")
        except (ValueError, KeyError, TypeError) as exc:
            return self._send(400, {"error": f"bad request: {exc}"})
        with _grade_lock:
            try:
                doc = grade(rubric, trajectory)
            except Exception as exc:  # the verifier must hear about it, not time out
                return self._send(500, {"error": f"grading crashed: {exc!r}"})
        self._send(200, doc)


def make_server(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def health_probe() -> int:
    """Exit status for compose's healthcheck. Never proxied: it is loopback."""
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{_port()}/healthz", timeout=5) as resp:
            return 0 if resp.status == 200 else 1
    except Exception as exc:
        print(f"[codexbridge] unhealthy: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--health"]:
        return health_probe()
    _state["credential_error"] = install_credential()
    host = os.environ.get("JUDGE_HOST", "0.0.0.0")
    srv = make_server(host, _port())
    print(f"[codexbridge] listening on {host}:{_port()} model={_model()} "
          f"ready={not_ready() or 'yes'}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
