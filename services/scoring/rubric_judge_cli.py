#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_out_path: Path | None = None
_token_out: Path | None = None


def _load_criteria(rubric_path: Path) -> list[dict]:
    """Load the bundle rubric, or refuse.

    An unrecognised shape used to return an empty list. That is the worst
    available outcome: zero criteria grade cleanly, _compute_scores divides a
    zero pool, and the run reports a finished rubric channel that judged
    nothing. Raising turns a silent wrong answer into a loud one, and matches
    rubric_judge._load_rubric, which refuses rather than returning empty.
    """
    raw = json.loads(rubric_path.read_text())
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        if isinstance(raw.get("criteria"), list):
            return raw["criteria"]
        if isinstance(raw.get("rubric"), list):
            return raw["rubric"]
    raise ValueError(
        f"{rubric_path} must be a list, {{'criteria': [...]}}, or {{'rubric': [...]}}, "
        f"got {type(raw).__name__}"
    )


def _render_trajectory(traj: dict, max_chars: int = 10000) -> str:
    parts: list[str] = []
    for step in traj.get("steps", []):
        args = step.get("arguments", {})
        resp = step.get("response", "")
        args_s = json.dumps(args)[:400] if not isinstance(args, str) else args[:400]
        resp_s = json.dumps(resp)[:400] if not isinstance(resp, str) else str(resp)[:400]
        parts.append(f"tool={step.get('tool')} args={args_s} → {resp_s}")
    final = traj.get("final_message", "")
    if final:
        parts.append(f"Final: {final[:2000]}")
    joined = "\n".join(parts)
    return joined[:max_chars] + ("\n...[truncated]" if len(joined) > max_chars else "")


# _OUTPUT_SCHEMA lived here. It was the Agent SDK's structured-output
# contract; the direct transport parses the reply with _parse_judge_json,
# which already handled bare, fenced, and prose-wrapped JSON.


# The models this judge grades with, spelled the way `codex exec -m` wants
# them. The transport (ported from devops-projects' judge council `codex/`
# seat) is the locally-installed Codex CLI run as a subprocess. It spends the
# operator's ChatGPT subscription quota rather than metered API credit, and
# needs no OPENAI_API_KEY, no bridge server, and no generated key — only a
# `codex login` this machine already holds.
CODEX_MODELS = ("gpt-5.6-sol",)

CODEX_EXEC_ARGS = ("exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check")

# Measured 2026-09-01 on codex-cli 0.146.0: a trivial one-line prompt still
# reported input_tokens=14564 (cached_input_tokens=11008). That is Codex's own
# agent scaffold, carried on EVERY call on top of the grading prompt. It is
# quota, not dollars, but it makes this judge's token counts non-comparable
# to an HTTP judge's.
CODEX_SCAFFOLD_TOKENS_OBSERVED = 14_564

# Retry policy for the subprocess transport. Transient failures here look
# like nonzero exits or an empty event stream rather than HTTP 429s, but the
# cause is usually the same hot rate-limit window right after an agent run.
_BACKOFF_BASE_SEC = 15.0
_BACKOFF_CAP_SEC = 120.0
_MAX_ATTEMPTS = 4


def _codex_cli() -> str:
    """Path to the Codex CLI, or "" when it is not installed."""
    return shutil.which("codex") or ""


def _codex_credential_error() -> str:
    """Why the Codex CLI is unusable as a judge, or "" if it is ready.

    Asks the CLI itself (`codex login status`) rather than reading its
    credential store: the answer is what actually matters, and no secret need
    be touched to get it.
    """
    cli = _codex_cli()
    if not cli:
        return (
            "codex CLI not found on PATH; the rubric judge shells out to "
            "`codex exec`, so it must run where the CLI is installed and "
            "logged in (the host, not the task container)"
        )
    try:
        proc = subprocess.run(
            [cli, "login", "status"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as err:
        return f"could not run `codex login status`: {err}"
    out = f"{proc.stdout} {proc.stderr}".strip()
    # A plain substring test for "logged in" would also match "Not logged in",
    # so a nonzero exit or an explicit denial each fail on their own.
    if proc.returncode != 0 or "not logged in" in out.lower():
        return f"codex CLI is not logged in (run `codex login`): {out[:120]}"
    return ""


def _preflight(model: str) -> str | None:
    """Confirm the judge can reach its backend before grading starts.

    A backend discovered per-criterion arrives as a rubric full of failures
    that still writes a score file, which reads like a graded run. For a
    Codex model the whole check is the CLI's own `codex login status`; a
    non-Codex model returns None here and is refused by _run_judge instead.
    """
    if model not in CODEX_MODELS:
        return None
    return _codex_credential_error() or None


def _judge_prompt(criteria: list[dict], traj_ctx: str, final_ctx: str) -> str:
    """The grading prompt. Shared, so the two transports grade identically."""
    criteria_payload = json.dumps(
        [
            {
                "number": c.get("number"),
                "criterion": c.get("criterion"),
                "evaluation_target": c.get("evaluation_target", "trajectory"),
                "is_positive": c.get("is_positive", True),
            }
            for c in criteria
        ],
        indent=2,
    )

    prompt = (
        "You are grading an AI agent's trial output against a rubric.\n\n"
        "## Trajectory\n"
        + traj_ctx
        + "\n\n## Final Message\n"
        + (final_ctx or "(none)")
        + "\n\n## Criteria\n"
        + criteria_payload
        + "\n\nFor each criterion, set satisfied=true when the criterion's statement "
        "is TRUE of the agent's behavior, and false when it is not.\n"
        "Read is_positive carefully. A criterion with is_positive=false states a "
        "mistake, so satisfied=true there means the agent MADE that mistake and "
        "satisfied=false means it avoided it. Judge the statement itself, never "
        "whether the agent did well: on a is_positive=false criterion an agent that "
        "behaved correctly gets satisfied=false.\n"
        "Use trajectory for evaluation_target=trajectory or trajectory_and_state.\n"
        "Use final message for evaluation_target=final_answer.\n"
        "Return JSON: {results: [{number, satisfied (bool), justification (one sentence)}]}"
    )
    return prompt


def _codex_exec(model: str, prompt: str, timeout: float) -> tuple[str, dict]:
    """One `codex exec` call: prompt in on stdin, (reply_text, usage) out.

    The single implementation of the subprocess plumbing — `_run_judge_codex`
    here and `rubric_judge._call_judge_once` both grade through it, so the
    argv, the sandbox pinning, and the JSONL event parsing cannot drift apart.
    Raises JudgeResponseError on a nonzero exit or an empty event stream;
    retry policy belongs to the caller.
    """
    cli = _codex_cli()
    if not cli:
        raise JudgeResponseError("codex CLI not found on PATH")
    proc = subprocess.run(
        [cli, *CODEX_EXEC_ARGS, "-m", model],
        input=prompt, capture_output=True, text=True, timeout=timeout,
        # A scratch cwd, so the read-only agent cannot even see the trial
        # tree it is judging or mistake it for its own workspace.
        cwd=tempfile.gettempdir(),
    )
    if proc.returncode != 0:
        raise JudgeResponseError(
            f"codex exec exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()[:300]}"
        )
    message, usage_obj = "", {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") or {}
        if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            # Keep the LAST message: the agent may narrate before it
            # delivers the verdict JSON.
            message = item["text"]
        if event.get("type") == "turn.completed":
            usage_obj = event.get("usage") or {}
    if not message.strip():
        raise JudgeResponseError("codex exec produced no agent message")
    return message, usage_obj


def _run_judge_codex(
    criteria: list[dict], traj_ctx: str, final_ctx: str, model: str
) -> list[dict]:
    """Grade by running the local Codex CLI. No server, no key, no bridge.

    Ported from devops-projects' judge council `_call_judge_codex`. It drives
    the CLI the way it is meant to be driven (`codex exec`) rather than
    extracting the stored credential and replaying it against api.openai.com:
    that credential is scoped to Codex traffic, and impersonating the Codex
    client to get around that is neither reliable nor ours to do.

    Two consequences worth knowing at the call site:

      * Codex is an AGENT, not a completion endpoint. It is pinned to a
        read-only sandbox and run in a scratch cwd so the judge cannot mutate
        the trial it is grading, but it may still take a turn or two to
        answer, so this is slower than an HTTP call.
      * Every call carries Codex's own ~14.5K-token scaffold
        (CODEX_SCAFFOLD_TOKENS_OBSERVED) on top of the grading prompt.
    """
    # A missing CLI is a configuration fact, not a transient failure: refuse
    # before the retry loop rather than backing off three times into it.
    if not _codex_cli():
        raise JudgeResponseError("codex CLI not found on PATH")
    prompt = _judge_prompt(criteria, traj_ctx, final_ctx)
    timeout = float(os.environ.get("JUDGE_CODEX_TIMEOUT", "600"))

    last: Exception | None = None
    text, usage = "", {}
    for n in range(1, _MAX_ATTEMPTS + 1):
        try:
            text, usage = _codex_exec(model, prompt, timeout)
            break
        except (JudgeResponseError, OSError, subprocess.SubprocessError) as err:
            last = err
            if n >= _MAX_ATTEMPTS:
                raise JudgeResponseError(f"codex judge failed: {err}") from err
            delay = min(_BACKOFF_BASE_SEC * 2 ** (n - 1), _BACKOFF_CAP_SEC)
            print(
                f"[judge] codex/{model}: {str(err)[:120]} "
                f"(attempt {n}/{_MAX_ATTEMPTS}), retrying in {delay:.0f}s",
                file=sys.stderr,
            )
            time.sleep(delay)
    else:  # pragma: no cover - the loop always breaks or raises
        raise JudgeResponseError(f"codex judge failed: {last}")

    _record_usage_codex(usage, model)

    parsed = _parse_judge_json(text) if text else None
    if isinstance(parsed, dict) and "results" in parsed:
        return parsed.get("results", [])
    raise JudgeResponseError(
        "judge returned no parseable JSON; reply began: "
        + (text[:400] if text else "(empty)")
    )


def _record_usage_codex(usage: dict, model: str) -> None:
    """Same file and field names as the old bridge path, from `codex exec` usage.

    Codex reports OpenAI-style INCLUSIVE input counts: cached_input_tokens is
    part of input_tokens. The cached portion is subtracted so the fields stay
    disjoint, matching how every other judge line is read downstream.

    Written best-effort so scripts/finance_reporter.py always sees the usage
    that was incurred: never raises, never blocks grading.
    """
    if _token_out is None:
        return
    try:
        cached = int(usage.get("cached_input_tokens", 0) or 0)
        total_in = int(usage.get("input_tokens", 0) or 0)
        line = {
            "model_name": model or os.getenv("JUDGE_MODEL", ""),
            "judge_input_tokens": max(0, total_in - cached),
            "judge_output_tokens": int(usage.get("output_tokens", 0) or 0),
            "judge_input_cache_tokens": cached,
            "judge_output_cache_tokens": 0,
            # `codex exec` spends the operator's ChatGPT subscription quota,
            # not metered credit, so the dollar cost is genuinely zero.
            # Reporting an invented one would be worse than reporting zero.
            "judge_cost_usd": 0.0,
        }
        _token_out.parent.mkdir(parents=True, exist_ok=True)
        _token_out.write_text(json.dumps([line], indent=2))
    except Exception:
        pass


async def _run_judge(
    criteria: list[dict], traj_ctx: str, final_ctx: str, model: str
) -> list[dict]:
    """Grade one trial. Codex only, over the local CLI.

    This used to dispatch: a Codex model went to codex-bridge over HTTP and,
    before that, through claude_agent_sdk. Both branches are gone. The judge
    is gpt-5.6-sol through `codex exec`, and keeping the other transports
    meant keeping a bridge server, its generated key, and Docker networking
    as live concerns in a path that no longer touches any of them.
    """
    if model not in CODEX_MODELS:
        raise JudgeResponseError(
            f"{model!r} is not a model this judge grades with. The rubric judge "
            f"runs on {list(CODEX_MODELS)} through the local `codex` CLI; pass "
            "--model, or set JUDGE_MODEL, to one of those."
        )
    return _run_judge_codex(criteria, traj_ctx, final_ctx, model)


class JudgeResponseError(RuntimeError):
    """The judge ran but its answer could not be read as rubric JSON."""


def _parse_judge_json(text: str):
    """Best-effort JSON out of a model reply: bare, fenced, or embedded in prose."""
    text = text.strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")      # JSON wrapped in prose
    if 0 <= start < end:
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            pass
    return None


def _compute_scores(criteria: list[dict], results: list[dict]) -> dict:
    by_num = {str(r.get("number", "")): r for r in results}
    pos_total = pos_earned = neg_total = neg_hit = 0.0
    per_criterion: list[dict] = []

    for c in criteria:
        num = str(c.get("number", ""))
        weight = float(c.get("score", 1))
        is_pos = bool(c.get("is_positive", True))
        r = by_num.get(num, {})
        satisfied = bool(r.get("satisfied", False))

        if is_pos:
            pos_total += weight
            if satisfied:
                pos_earned += weight
        else:
            neg_total += weight
            if satisfied:
                neg_hit += weight

        per_criterion.append(
            {
                "number": num,
                "criterion": c.get("criterion"),
                "type": c.get("type"),
                "evaluation_target": c.get("evaluation_target"),
                "importance": c.get("importance"),
                "weight": weight,
                "is_positive": is_pos,
                "satisfied": satisfied,
                "justification": r.get("justification", ""),
            }
        )

    rc = (pos_earned / pos_total) if pos_total else 1.0
    rb = (neg_hit / neg_total) if neg_total else 0.0
    return {
        "score": round(rc * (1.0 - rb), 4),
        "rc": round(rc, 4),
        "rb": round(rb, 4),
        "rubric_passed": rc >= 0.999999 and rb <= 0.000001,
        "per_criterion": per_criterion,
    }


def main() -> None:
    global _out_path, _token_out

    ap = argparse.ArgumentParser()
    ap.add_argument("--rubric", required=True)
    ap.add_argument("--trajectory", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--token-output", default=None,
                    help="write the judge's own token usage here, in the finance "
                         "API's judge_lines shape (read by scripts/finance_reporter.py)")
    ap.add_argument("--model", default=os.getenv("JUDGE_MODEL", "gpt-5.6-sol"))
    a = ap.parse_args()

    _out_path = Path(a.output)
    _token_out = Path(a.token_output) if a.token_output else None
    rubric_path = Path(a.rubric)
    traj_path = Path(a.trajectory)

    if not rubric_path.exists():
        print(f"rubric not found: {rubric_path}", file=sys.stderr)
        sys.exit(1)
    if not traj_path.exists():
        print(f"trajectory not found: {traj_path}", file=sys.stderr)
        sys.exit(1)

    # Route to the judge backend before any grading starts. A misconfigured
    # backend that is discovered per-criterion arrives as a rubric full of
    # failures that still writes a score file, which reads like a graded run.
    routing_error = _preflight(a.model)
    if routing_error:
        print(routing_error, file=sys.stderr)
        sys.exit(2)

    criteria = _load_criteria(rubric_path)
    if not criteria:
        print("no LLM-graded criteria found in rubric", file=sys.stderr)
        _out_path.parent.mkdir(parents=True, exist_ok=True)
        _out_path.write_text(
            json.dumps(
                {"score": 0.0, "rc": 0.0, "rb": 0.0, "rubric_passed": False, "per_criterion": []},
                indent=2,
            )
        )
        sys.exit(0)

    traj = json.loads(traj_path.read_text())
    traj_ctx = _render_trajectory(traj)
    final_ctx = traj.get("final_message", "")

    print(f"Grading {len(criteria)} criteria with {a.model}")
    results = asyncio.run(_run_judge(criteria, traj_ctx, final_ctx, a.model))
    doc = _compute_scores(criteria, results)

    _out_path.parent.mkdir(parents=True, exist_ok=True)
    _out_path.write_text(json.dumps(doc, indent=2))
    print(f"score={doc['score']} rc={doc['rc']} rb={doc['rb']} passed={doc['rubric_passed']}")
    print(f"Written: {_out_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback

        traceback.print_exc()
        out = _out_path or Path("/logs/verifier/rubric_breakdown.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"score": 0.0, "rc": 0.0, "rb": 0.0, "rubric_passed": False, "per_criterion": [], "error": str(exc)},
                indent=2,
            )
        )
        sys.exit(1)
