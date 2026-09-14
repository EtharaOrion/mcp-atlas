#!/usr/bin/env python3
"""Grade the rubric by asking the judge container, not by judging here.

tests/test.sh calls this where it used to call rubric_judge_cli.py, with the
same four flags, so a bundle switches by changing one path. It runs in `main`,
the container the agent just used, which is exactly why no judge runs here: the
codex login never enters `main`, and the grading model never sees anything but
the one run it is sent.

The judge is the `judge` service in the bundle's docker-compose.yaml
(tools/judge/codexbridge.py). What it receives is this run's rubric and this
run's trajectory, as request bodies -- it has no folder of runs to look in.

Writes next to --output:
  rubric_breakdown.json   only when the judge returned real verdicts
  judge_tokens.json       whenever the judge reported usage (--token-output)
  judge_container.json    always: whether the rubric was graded in the judge
                          container, and if not, why. tests/test_judge_container.py
                          and test.sh's reward step read it.

Exit 0 only on real verdicts. Anything else exits 1, which test.sh turns into
rubric_judge_failed.txt; scripts/run_task.sh then re-grades on the host.

Env: JUDGE_TOKEN (required), JUDGE_URL (http://judge:8770),
     JUDGE_WAIT_SEC (120), JUDGE_REQUEST_TIMEOUT_SEC (1200 -- inside the
     bundle's [verifier] timeout_sec of 1800, which also covers steps 1-5).
Stdlib only: `main` has no requests/httpx.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

MARKER_NAME = "judge_container.json"
GRADED_IN = "judge-container"

# Never through squid. The judge is a sibling on the compose bridge; under
# network isolation main's HTTP(S)_PROXY points at egress-proxy, which would
# deny it. An explicit empty ProxyHandler keeps that true even if NO_PROXY drifts.
_opener = build_opener(ProxyHandler({}))


def _error_body(exc: HTTPError) -> str:
    try:
        doc = json.loads(exc.read() or b"{}")
        return str(doc.get("error") or doc.get("reason") or doc)
    except (ValueError, OSError):
        return str(exc)


def wait_until_healthy(url: str, wait_sec: float) -> str | None:
    """None once /healthz answers 200, else the last reason it did not."""
    deadline = time.monotonic() + wait_sec
    last = "judge never answered"
    while True:
        try:
            with _opener.open(f"{url}/healthz", timeout=5) as resp:
                if resp.status == 200:
                    return None
                last = f"healthz returned {resp.status}"
        except HTTPError as exc:
            last = f"healthz {exc.code}: {_error_body(exc)}"
        except (URLError, OSError) as exc:
            last = f"judge unreachable at {url}: {exc}"
        if time.monotonic() >= deadline:
            return last
        time.sleep(2)


def request_grade(url: str, token: str, rubric: dict, trajectory: dict,
                  timeout: float) -> dict:
    body = json.dumps({"rubric": rubric, "trajectory": trajectory}).encode()
    req = Request(f"{url}/grade", data=body, method="POST",
                  headers={"Content-Type": "application/json", "x-judge-token": token})
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except HTTPError as exc:
        return {"ok": False, "reason": f"judge answered {exc.code}: {_error_body(exc)}"}
    except (URLError, OSError, ValueError) as exc:
        return {"ok": False, "reason": f"grade request failed: {exc}"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rubric", required=True)
    ap.add_argument("--trajectory", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--token-output", default=None)
    a = ap.parse_args(argv)

    url = os.environ.get("JUDGE_URL", "http://judge:8770").rstrip("/")
    token = os.environ.get("JUDGE_TOKEN", "")
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    marker = out.parent / MARKER_NAME

    def finish(doc: dict) -> int:
        ok = bool(doc.get("ok"))
        marker.write_text(json.dumps({
            "ok": ok,
            "graded_in": doc.get("graded_in") if ok else None,
            "reason": doc.get("reason"),
            "url": url,
            "model": doc.get("model"),
            "codex_version": doc.get("codex_version"),
            "returncode": doc.get("returncode"),
        }, indent=2))
        if doc.get("log_tail"):
            print(doc["log_tail"].rstrip())
        if doc.get("tokens") is not None and a.token_output:
            Path(a.token_output).write_text(json.dumps(doc["tokens"], indent=2))
        if ok:
            out.write_text(json.dumps(doc["breakdown"], indent=2))
            print(f"[judge-client] graded in {doc.get('graded_in')} by {doc.get('model')} -> {out}")
            return 0
        print(f"[judge-client] rubric NOT graded in the judge container: {doc.get('reason')}",
              file=sys.stderr)
        return 1

    if not token:
        return finish({"ok": False, "reason": "JUDGE_TOKEN is not set in the verifier "
                                             "environment (task.toml [verifier.env])"})
    try:
        rubric = json.loads(Path(a.rubric).read_text())
        trajectory = json.loads(Path(a.trajectory).read_text())
    except (OSError, ValueError) as exc:
        return finish({"ok": False, "reason": f"cannot read inputs: {exc}"})

    why = wait_until_healthy(url, float(os.environ.get("JUDGE_WAIT_SEC", "120")))
    if why:
        return finish({"ok": False, "reason": why})
    return finish(request_grade(url, token, rubric, trajectory,
                                float(os.environ.get("JUDGE_REQUEST_TIMEOUT_SEC", "1200"))))


if __name__ == "__main__":
    sys.exit(main())
