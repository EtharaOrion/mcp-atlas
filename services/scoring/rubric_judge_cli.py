#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_out_path: Path | None = None


def _load_criteria(rubric_path: Path) -> list[dict]:
    raw = json.loads(rubric_path.read_text())
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        if "criteria" in raw:
            return raw["criteria"]
    return []


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


_OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "number": {"type": "string"},
                        "satisfied": {"type": "boolean"},
                        "justification": {"type": "string"},
                    },
                    "required": ["number", "satisfied", "justification"],
                },
            }
        },
        "required": ["results"],
    },
}


async def _run_judge(criteria: list[dict], traj_ctx: str, final_ctx: str, model: str) -> list[dict]:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

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
        + "\n\nFor each criterion, judge whether the agent's behavior satisfies it.\n"
        "Use trajectory for evaluation_target=trajectory or trajectory_and_state.\n"
        "Use final message for evaluation_target=final_answer.\n"
        "Return JSON: {results: [{number, satisfied (bool), justification (one sentence)}]}"
    )

    options = ClaudeAgentOptions(
        allowed_tools=[],
        permission_mode="acceptEdits",
        model=model,
        max_turns=2,
        output_format=_OUTPUT_SCHEMA,
        effort="low",
    )

    messages: list = []
    async with ClaudeSDKClient(options) as client:
        await client.query(prompt=prompt)
        async for msg in client.receive_response():
            messages.append(msg)

    for msg in reversed(messages):
        if hasattr(msg, "structured_output") and msg.structured_output:
            raw = msg.structured_output
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            return parsed.get("results", []) if isinstance(parsed, dict) else []
        if hasattr(msg, "result") and msg.result:
            text = msg.result.strip()
            if text.startswith("```"):
                lines = text.split("\n")[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)
            parsed = json.loads(text)
            return parsed.get("results", []) if isinstance(parsed, dict) else []
    return []


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
    global _out_path

    ap = argparse.ArgumentParser()
    ap.add_argument("--rubric", required=True)
    ap.add_argument("--trajectory", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--model", default=os.getenv("JUDGE_MODEL", "claude-sonnet-4-6"))
    a = ap.parse_args()

    _out_path = Path(a.output)
    rubric_path = Path(a.rubric)
    traj_path = Path(a.trajectory)

    if not rubric_path.exists():
        print(f"rubric not found: {rubric_path}", file=sys.stderr)
        sys.exit(1)
    if not traj_path.exists():
        print(f"trajectory not found: {traj_path}", file=sys.stderr)
        sys.exit(1)

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
