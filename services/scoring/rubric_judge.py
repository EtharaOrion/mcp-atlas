from __future__ import annotations

import argparse
import json
import os
import re
import sys
from json import JSONDecodeError
from pathlib import Path
from typing import Any

import litellm
import yaml

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.scoring.trajectory_io import load_trajectory


_KEEP_TAIL = 20
_MAX_JUDGE_RETRIES = 3
_DEFAULT_BASE_URL = "http://localhost:4000/v1"
_DEFAULT_API_KEY = "cc-bridge-local"
_JUDGE_SYSTEM_PROMPT = (
    'You grade AI agent trajectories against rubric criteria. '
    'Return only JSON: {"score": <float 0..1>, "reason": "<one sentence>"}.'
)


def _load_rubric(rubric_path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(rubric_path.read_text())
    if isinstance(data, dict) and "rubric" in data:
        return list(data["rubric"])
    if isinstance(data, list):
        return list(data)
    raise ValueError(f"Rubric file must be a list or {{'rubric': [...]}}, got {type(data).__name__}")


def _normalize_weights(criteria: list[dict[str, Any]]) -> list[float]:
    raw = [float(c.get("weight", 1.0)) for c in criteria]
    total = sum(raw)
    # Uniform weights when total is zero — otherwise final_reward is undefined.
    if total <= 0:
        n = len(raw)
        return [1.0 / n for _ in raw] if n else []
    return [w / total for w in raw]


def _truncate_trajectory(trajectory: dict[str, Any]) -> dict[str, Any]:
    messages = list(trajectory.get("messages") or [])
    if len(messages) <= _KEEP_TAIL + 1:
        return trajectory

    first_user_idx = next(
        (i for i, m in enumerate(messages) if m.get("role") == "user"),
        None,
    )
    tail = messages[-_KEEP_TAIL:]
    tail_start = len(messages) - _KEEP_TAIL

    kept: list[dict[str, Any]] = []
    if first_user_idx is not None and first_user_idx < tail_start:
        kept.append(messages[first_user_idx])
        dropped = tail_start - (first_user_idx + 1)
        if dropped > 0:
            kept.append({"role": "system", "content": f"... [truncated {dropped} messages]"})
    kept.extend(tail)

    truncated = dict(trajectory)
    truncated["messages"] = kept
    return truncated


def _infer_task_id_and_run(trajectory_path: Path) -> tuple[str | None, int | None]:
    parents = list(trajectory_path.parents)
    run_dir = parents[0] if parents else None
    task_dir = parents[1] if len(parents) > 1 else None

    run_num: int | None = None
    if run_dir is not None:
        m = re.match(r"^run(\d+)$", run_dir.name)
        if m:
            run_num = int(m.group(1))

    task_id = task_dir.name if task_dir is not None else None
    return task_id, run_num


def _build_judge_messages(
    task_prompt: str,
    criterion: dict[str, Any],
    trajectory: dict[str, Any],
    extra_reminder: str | None = None,
) -> list[dict[str, str]]:
    user_parts = [
        f"Task prompt:\n{task_prompt}",
        f"Rubric criterion:\n{json.dumps({'id': criterion.get('id'), 'description': criterion.get('description'), 'weight': criterion.get('weight')}, indent=2)}",
        f"Trajectory (JSON):\n{json.dumps(trajectory, indent=2, default=str)}",
    ]
    if extra_reminder:
        user_parts.append(extra_reminder)
    return [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def _extract_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except JSONDecodeError:
        # Judge sometimes wraps JSON in prose or code fences despite response_format constraint.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _call_judge_once(
    model_for_call: str,
    api_base: str,
    api_key: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    response = litellm.completion(
        model=model_for_call,
        api_base=api_base,
        api_key=api_key,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    content = response["choices"][0]["message"]["content"]
    return _extract_json(content)


def _score_criterion(
    criterion: dict[str, Any],
    task_prompt: str,
    trajectory: dict[str, Any],
    model_for_call: str,
    api_base: str,
    api_key: str,
) -> tuple[float | None, str, str | None]:
    reminder: str | None = None
    last_err: str | None = None
    for attempt in range(_MAX_JUDGE_RETRIES):
        messages = _build_judge_messages(task_prompt, criterion, trajectory, reminder)
        try:
            parsed = _call_judge_once(model_for_call, api_base, api_key, messages)
            score = float(parsed.get("score"))
            score = max(0.0, min(1.0, score))
            reason = str(parsed.get("reason", ""))
            return score, reason, None
        except (JSONDecodeError, ValueError, TypeError, KeyError) as e:
            last_err = f"{type(e).__name__}: {e}"
            reminder = (
                "IMPORTANT: your previous response was not valid JSON matching "
                '{"score": <float 0..1>, "reason": "<one sentence>"}. '
                "Return ONLY that JSON object, no prose, no code fences."
            )
    return None, "", last_err or "judge failed to return valid JSON after 3 retries"


def score_rubric(
    trajectory_path: Path,
    rubric_path: Path,
    task_prompt: str,
    output_path: Path,
    judge_model: str = "claude-sonnet-4-6",
    judge_base_url: str | None = None,
    judge_api_key: str | None = None,
) -> dict:
    trajectory_path = Path(trajectory_path)
    rubric_path = Path(rubric_path)
    output_path = Path(output_path)

    api_base = judge_base_url or os.environ.get("EVAL_LLM_BASE_URL") or _DEFAULT_BASE_URL
    api_key = judge_api_key or os.environ.get("EVAL_LLM_API_KEY") or _DEFAULT_API_KEY
    # Prefix with `openai/` so litellm routes through the OpenAI-compatible path and
    # honours api_base (native Anthropic routing ignores it).
    model_for_call = judge_model if "/" in judge_model else f"openai/{judge_model}"

    trajectory = load_trajectory(trajectory_path)
    criteria = _load_rubric(rubric_path)
    normalized = _normalize_weights(criteria)
    truncated = _truncate_trajectory(trajectory)

    task_id, run_num = _infer_task_id_and_run(trajectory_path)

    results: list[dict[str, Any]] = []
    judge_failures = 0
    final_reward = 0.0
    any_success = False

    for criterion, norm_w in zip(criteria, normalized):
        score, reason, err = _score_criterion(
            criterion,
            task_prompt,
            truncated,
            model_for_call,
            api_base,
            api_key,
        )
        entry: dict[str, Any] = {
            "id": criterion.get("id"),
            "weight": float(criterion.get("weight", 1.0)),
            "normalized_weight": norm_w,
            "score": score,
            "reason": reason,
        }
        if err is not None:
            entry["error"] = "judge failed to return valid JSON after 3 retries"
            judge_failures += 1
        else:
            any_success = True
            final_reward += norm_w * (score or 0.0)
        results.append(entry)

    rubric_pct = (final_reward * 100.0) if any_success else None

    output = {
        "task_id": task_id,
        "run": run_num,
        "judge_model": judge_model,
        "criteria": results,
        "judge_failures": judge_failures,
        "final_reward": final_reward if any_success else 0.0,
        "rubric_weights_percentage": rubric_pct,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))
    return output


def _cli() -> None:
    p = argparse.ArgumentParser(description="Score a trajectory against a rubric using an LLM judge.")
    p.add_argument("--trajectory", required=True, type=Path)
    p.add_argument("--rubric", required=True, type=Path)
    p.add_argument("--task-prompt", required=True, type=str)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--judge-model", default="claude-sonnet-4-6")
    args = p.parse_args()

    result = score_rubric(
        trajectory_path=args.trajectory,
        rubric_path=args.rubric,
        task_prompt=args.task_prompt,
        output_path=args.output,
        judge_model=args.judge_model,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli()
