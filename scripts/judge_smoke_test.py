#!/usr/bin/env python3
"""Smoke test the rubric judge against a codex-bridge-shaped server.

Runs both rubric judges end to end: `rubric_judge_cli._run_judge_claude`,
which is what `tests/test.sh` grades with, and `score_rubric`. By default it talks to an in-process
stub that speaks the subset of codex-bridge this judge uses, so the whole path
is exercised without spending subscription calls:

    preflight -> provider_route -> litellm anthropic transport
              -> /v1/messages -> _extract_json -> 11-trial discipline

The stub is the point, not a shortcut. The failures this catches are wiring
failures, and every one of them is invisible until a request is actually
attempted: an `openai/` prefix posting to a chat/completions route the bridge
does not serve, an api_base carrying a `/v1` that litellm then doubles, a
`response_format` the Anthropic Messages API rejects. A mocked litellm would
assert none of that, because it is litellm's own URL and payload construction
that is under test.

Pass --live to run against a real `codex-bridge serve` instead. That is the only
way to confirm credentials and the real model, and it does consume plan calls.

    python3 scripts/judge_smoke_test.py           # stub, free, no bridge needed
    python3 scripts/judge_smoke_test.py --live    # real bridge, real Codex
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services" / "scoring"))

PASS = "  ok   "
FAIL = " FAIL  "

# What the stub judge returns for every criterion. Deliberately mid-range: a 0
# or a 1 could be produced by a failure path that defaults, and would not prove
# the value came from the reply.
STUB_SCORE = 0.75
STUB_REASON = "stub judge reply"


class _Handler(BaseHTTPRequestHandler):
    """The three routes the judge path touches, shaped like codex-bridge."""

    served_models = ["gpt-5.6-sol", "gpt-5.6-luna"]
    seen_paths: list[str] = []

    def log_message(self, *args):  # keep the smoke output readable
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        return bool(
            self.headers.get("x-api-key") or self.headers.get("Authorization")
        )

    def do_GET(self):
        type(self).seen_paths.append(f"GET {self.path}")
        if self.path == "/health":
            return self._json({"status": "ok", "capabilities": {}})
        if not self._authed():
            return self._json({"error": "missing key"}, 401)
        if self.path == "/v1/models":
            return self._json(
                {"data": [{"id": m} for m in type(self).served_models]}
            )
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        type(self).seen_paths.append(f"POST {self.path}")
        if not self._authed():
            return self._json({"error": "missing key"}, 401)
        # Only the two routes codex-bridge actually serves. Anything else means
        # a judge routed to a transport this bridge does not have, and a 404
        # here makes that a visible smoke failure rather than a silent one.
        if self.path not in ("/v1/messages", "/v1/responses"):
            return self._json({"error": "no such route"}, 404)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")

        # /v1/responses is the production rubric judge: rubric_judge_cli posts
        # the whole rubric once and expects a results array back.
        if self.path == "/v1/responses":
            verdicts = {"results": [
                {"number": str(n), "satisfied": True, "justification": "stub verdict"}
                for n in (1, 2)
            ]}
            return self._json({
                "id": "resp_stub",
                "model": body.get("model", "gpt-5.6-sol"),
                "output_text": json.dumps(verdicts),
                "usage": {"input_tokens": 40, "output_tokens": 12},
            })

        if "response_format" in body:
            return self._json(
                {"error": "response_format is not supported on messages"}, 400
            )
        self._json({
            "id": "msg_stub",
            "type": "message",
            "role": "assistant",
            "model": body.get("model", "gpt-5.6-sol"),
            "content": [{
                "type": "text",
                "text": json.dumps({"score": STUB_SCORE, "reason": STUB_REASON}),
            }],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 10},
        })


def start_stub() -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _rubric(tmp: Path) -> tuple[Path, Path]:
    rubric = tmp / "rubric.json"
    # _load_rubric accepts a bare list or {"rubric": [...]}. The shipped bundles
    # store {"criteria": [...]}, which rubric_judge_cli converts before calling
    # score_rubric; this exercises score_rubric's own contract.
    rubric.write_text(json.dumps({"rubric": [
        {"id": "c1", "criterion": "The listing was activated.", "weight": 1.0},
        {"id": "c2", "criterion": "The price was recomputed.", "weight": 1.0},
    ]}))
    trajectory = tmp / "trajectory.json"
    trajectory.write_text(json.dumps({
        "steps": [{"tool": "LightEtsy_update_listing", "args": {"listing_id": 1020}}],
        "final_message": "Listing 1020 is live at 405.00.",
    }))
    return rubric, trajectory


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="run against a real codex-bridge instead of the stub")
    ap.add_argument("--model", default=None)
    ap.add_argument("--trials", type=int, default=2,
                    help="override RUBRIC_JUDGE_TRIALS for speed (stub only)")
    args = ap.parse_args()

    import os
    if not args.live:
        os.environ["RUBRIC_JUDGE_TRIALS"] = str(args.trials)

    import codex_bridge as cb

    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"[{PASS if ok else FAIL}] {name}" + (f"  {detail}" if detail else ""))
        if not ok:
            failures += 1

    model = args.model or cb.DEFAULT_BRIDGE_MODEL
    print(f"judge smoke test  model={model}  mode={'live' if args.live else 'stub'}\n")

    # --- routing, before anything is started ---
    check("codex model routes through anthropic",
          cb.provider_route(model) == f"anthropic/{model}",
          cb.provider_route(model))
    try:
        cb.provider_route("some-other-model")
        check("bare non-codex model is refused", False, "no exception raised")
    except cb.BridgeUnavailable:
        check("bare non-codex model is refused", True)

    server = None
    if args.live:
        root = cb.DEFAULT_ANTHROPIC_BASE_URL
        key = cb.api_key()
    else:
        server, root = start_stub()
        key = "stub-key"
        os.environ["CB_API_KEY"] = key

    try:
        # --- preflight ---
        try:
            status = cb.preflight(root=root, model=model,
                                  require_auth_file=args.live)
            check("preflight passes", True, status.detail)
        except cb.BridgeUnavailable as e:
            check("preflight passes", False, str(e))
            return 1

        check("run record marks the judge unpinned",
              status.as_record()["backend_pinned"] is False)

        # --- the production judge: rubric_judge_cli, the one test.sh runs ---
        #
        # This is the path that decides a real trial's rubric score. Checking
        # only score_rubric below would verify the transport nothing grades on.
        from services.scoring import rubric_judge_cli as cli

        _Handler.seen_paths.clear()
        os.environ["EVAL_LLM_BASE_URL"] = root
        criteria = [
            {"number": "1", "criterion": "The listing was activated.",
             "is_positive": True, "score": 5},
            {"number": "2", "criterion": "The price was recomputed.",
             "is_positive": True, "score": 3},
        ]
        check("production judge preflight passes", cli._preflight(model) is None,
              cli._preflight(model) or "")
        try:
            verdicts = cli._run_judge_claude(criteria, "traj", "final", model)
            check("production judge returned a verdict per criterion",
                  len(verdicts) == 2, f"{len(verdicts)} verdict(s)")
            check("verdicts carry the rubric fields",
                  all({"number", "satisfied", "justification"} <= set(v) for v in verdicts))
        except Exception as e:
            check("production judge graded", False, f"{type(e).__name__}: {e}")

        posted = [p for p in _Handler.seen_paths if p.startswith("POST")]
        check("production judge posted to /v1/responses",
              posted == ["POST /v1/responses"], str(posted))
        check("no Claude client in the production path",
              "claude_agent_sdk" not in sys.modules
              or sys.modules.get("claude_agent_sdk") is None)

        # --- the secondary judge: score_rubric, reached only by this script ---
        #
        # Reset the tracker so this section's route assertion sees only its own
        # requests, not the production judge's.
        _Handler.seen_paths.clear()
        from services.scoring.rubric_judge import score_rubric

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            rubric, trajectory = _rubric(tmp)
            out = tmp / "rubric_breakdown.json"
            result = score_rubric(
                trajectory_path=trajectory,
                rubric_path=rubric,
                task_prompt="Activate the draft listing at the recomputed price.",
                output_path=out,
                judge_model=model,
                judge_base_url=root,
                judge_api_key=key,
            )
            # Sampled inside the context: the temporary directory is gone by
            # the time the check below would run.
            wrote_output = out.is_file()

        criteria = result.get("criteria") or result.get("results") or []
        check("judge returned a per-criterion result", len(criteria) == 2,
              f"{len(criteria)} criteria")
        check("no judge failures", result.get("judge_failures", 0) == 0,
              f"judge_failures={result.get('judge_failures')}")
        check("output file written", wrote_output)

        if not args.live:
            posts = [p for p in _Handler.seen_paths if p.startswith("POST")]
            check("judge posted only to /v1/messages",
                  bool(posts) and all(p == "POST /v1/messages" for p in posts),
                  f"{len(posts)} post(s)")
            scores = [c.get("score") for c in criteria if isinstance(c, dict)]
            check("score came from the reply rather than a default",
                  bool(scores) and all(s == STUB_SCORE for s in scores),
                  str(scores))

        rel = next((c.get("reliability") for c in criteria
                    if isinstance(c, dict) and c.get("reliability")), None)
        check("reliability block present", rel is not None)
        if rel:
            check("every trial succeeded",
                  rel.get("trials_failed") == 0,
                  f"{rel.get('trials_succeeded')}/{rel.get('trials_requested')} trials")
    finally:
        if server is not None:
            server.shutdown()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
