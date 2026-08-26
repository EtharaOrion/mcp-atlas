from __future__ import annotations

import argparse
import math
import json
import os
import random
import re
import sys
import statistics
from json import JSONDecodeError
from pathlib import Path
from typing import Any

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

# --- judge-reliability discipline (trinity/CRUCIBLE.md verifier principle 5a) ---
#
# A single deterministic call yields a number with no reliability attached: it
# cannot distinguish a criterion the judge grades identically every time from
# one it grades differently depending on where the evidence sits in the prompt.
# Principle 5a therefore requires repeated trials, position randomization, and
# a conformal prediction set before a judged score is admissible.
#
# Trials are NOT free: each one is a model call, so a run costs
# _JUDGE_TRIALS times what a single-shot judge costs. RUBRIC_JUDGE_TRIALS
# lowers it, and lowering it below the floor is recorded honestly in the
# output as discipline_satisfied false rather than silently tolerated.
#
# The reported `score` remains the canonical trial: identical prompt ordering,
# temperature 0.0, exactly what this judge produced before the discipline
# existed. Downstream consumers compare scores for equality, so the headline
# number must not move. The trials add reliability metadata beside it, which
# is what principle 5a asks for: a low-confidence call narrows a conclusion,
# it never silently rewrites the score.
_JUDGE_TRIALS_FLOOR = 11
# The committed default. Declared as a literal so that reading this file
# answers "how many times does this judge grade a criterion" without having
# to resolve the environment, which is what both a reviewer and the audit
# instrument need. An operator may lower it with RUBRIC_JUDGE_TRIALS; when
# they do, _JUDGE_TRIALS_EFFECTIVE diverges and every emitted report records
# discipline_satisfied false rather than quietly claiming the discipline held.
_JUDGE_TRIALS = 11
_JUDGE_TRIALS_EFFECTIVE = max(1, int(os.environ.get("RUBRIC_JUDGE_TRIALS", _JUDGE_TRIALS)))
_STABILITY_TRIALS = _JUDGE_TRIALS_EFFECTIVE
_CONFORMAL_ALPHA = float(os.environ.get("RUBRIC_JUDGE_CONFORMAL_ALPHA", "0.1"))
# Width at or above this marks a criterion low-confidence. It narrows
# interpretation; it never changes the score or raises a reward.
_CONFORMAL_WIDE = float(os.environ.get("RUBRIC_JUDGE_CONFORMAL_WIDE", "0.25"))


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
    section_order: list[int] | None = None,
) -> list[dict[str, str]]:
    user_parts = [
        f"Task prompt:\n{task_prompt}",
        f"Rubric criterion:\n{json.dumps({'id': criterion.get('id'), 'description': criterion.get('description'), 'weight': criterion.get('weight')}, indent=2)}",
        f"Trajectory (JSON):\n{json.dumps(trajectory, indent=2, default=str)}",
    ]
    # Position randomization (principle 5a). The judge sees the same three
    # sections in a permuted order on non-canonical trials, so a score that
    # depends on where the evidence sits rather than on what it says shows up
    # as spread across trials instead of hiding inside one confident number.
    # extra_reminder stays last: it is a retry correction, not evidence.
    if section_order is not None:
        user_parts = [user_parts[idx] for idx in section_order]
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
    # Imported here rather than at module scope: litellm is a heavy runtime
    # dependency needed only to actually call a model. Deferring it keeps this
    # module importable, and therefore its reliability discipline testable,
    # in environments that do not carry it.
    import litellm
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
    section_order: list[int] | None = None,
) -> tuple[float | None, str, str | None]:
    reminder: str | None = None
    last_err: str | None = None
    for attempt in range(_MAX_JUDGE_RETRIES):
        messages = _build_judge_messages(
            task_prompt, criterion, trajectory, reminder, section_order
        )
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



def _permutations_for(criterion_id: str, n_trials: int) -> list[list[int] | None]:
    """Deterministic per-criterion section orderings, canonical trial first.

    Seeded from the criterion id so a re-run of the same rubric reproduces the
    same orderings. Reproducibility is not optional here: a grading pipeline
    whose prompts differ run to run cannot be replayed, and an unreplayable
    score is not evidence.

    Trial 0 is None, meaning the canonical order. That trial is the reported
    score, so the headline number is bit-identical to what this judge produced
    before the discipline existed.
    """
    rng = random.Random(f"rubric-judge-position::{criterion_id}")
    orders: list[list[int] | None] = [None]
    for _ in range(max(0, n_trials - 1)):
        perm = [0, 1, 2]
        rng.shuffle(perm)
        orders.append(perm)
    return orders


def _conformal_interval(scores: list[float], alpha: float) -> dict[str, Any]:
    """Split-conformal prediction set over the trial scores.

    Nonconformity is absolute deviation from the trial median. The radius is
    the ceil((n+1)(1-alpha))/n empirical quantile of those deviations, which is
    the standard finite-sample conformal quantile and gives at-least-(1-alpha)
    coverage under exchangeability of the trials.

    The calibration sample is the trial set itself, which is an honest
    limitation and is recorded rather than glossed: these trials are draws from
    one judge on one item, so the guarantee is over trial-to-trial variation
    and not over items. Width is the per-instance reliability indicator, which
    is what arXiv:2604.15302 finds correlates with judge unreliability.
    """
    n = len(scores)
    if n == 0:
        return {"available": False, "reason": "no successful trial"}
    med = statistics.median(scores)
    if n == 1:
        return {
            "available": False,
            "reason": "single trial cannot calibrate a prediction set",
            "median": med,
        }
    residuals = sorted(abs(s - med) for s in scores)
    rank = math.ceil((n + 1) * (1.0 - alpha))
    idx = min(max(rank, 1), n) - 1
    radius = residuals[idx]
    lo, hi = max(0.0, med - radius), min(1.0, med + radius)
    width = hi - lo
    return {
        "available": True,
        "alpha": alpha,
        "median": med,
        "radius": radius,
        "interval": [lo, hi],
        "width": width,
        "low_confidence": width >= _CONFORMAL_WIDE,
        "calibration": "self-calibrated on the trial sample; covers trial-to-trial variation, not item-to-item",
    }


def _score_criterion_with_discipline(
    criterion: dict[str, Any],
    task_prompt: str,
    trajectory: dict[str, Any],
    model_for_call: str,
    api_base: str,
    api_key: str,
    n_trials: int = _JUDGE_TRIALS_EFFECTIVE,
) -> tuple[float | None, str, str | None, dict[str, Any]]:
    """Grade one criterion under the principle 5a discipline.

    Returns the canonical score and reason unchanged, plus a reliability block.
    The canonical trial is trial 0; every later trial permutes section order.
    A trial that fails to parse after retries is dropped from the sample and
    counted, never substituted with a default, because a fabricated score would
    contaminate exactly the statistic this discipline exists to measure.
    """
    criterion_id = str(criterion.get("id", ""))
    orders = _permutations_for(criterion_id, n_trials)

    trial_scores: list[float] = []
    trial_records: list[dict[str, Any]] = []
    canonical_score: float | None = None
    canonical_reason = ""
    canonical_err: str | None = None

    for t, order in enumerate(orders):
        score, reason, err = _score_criterion(
            criterion, task_prompt, trajectory, model_for_call, api_base, api_key, order
        )
        if t == 0:
            canonical_score, canonical_reason, canonical_err = score, reason, err
        trial_records.append(
            {"trial": t, "section_order": order, "score": score, "error": err}
        )
        if score is not None:
            trial_scores.append(score)

    spread = (max(trial_scores) - min(trial_scores)) if trial_scores else None
    reliability: dict[str, Any] = {
        "trials_requested": n_trials,
        "trials_succeeded": len(trial_scores),
        "trials_failed": n_trials - len(trial_scores),
        "discipline_floor": _JUDGE_TRIALS_FLOOR,
        "discipline_satisfied": n_trials >= _JUDGE_TRIALS_FLOOR,
        "position_randomized": any(o is not None for o in orders),
        "trial_scores": trial_scores,
        "stability": {
            "spread": spread,
            "stdev": statistics.pstdev(trial_scores) if len(trial_scores) > 1 else None,
            "unstable": bool(spread is not None and spread > 0.0),
        },
        "conformal": _conformal_interval(trial_scores, _CONFORMAL_ALPHA),
        "trials": trial_records,
    }
    return canonical_score, canonical_reason, canonical_err, reliability


def re_grade(
    criterion: dict[str, Any],
    task_prompt: str,
    trajectory: dict[str, Any],
    model_for_call: str,
    api_base: str,
    api_key: str,
    n_trials: int = _STABILITY_TRIALS,
) -> dict[str, Any]:
    """Re-grade one criterion and return only its reliability block.

    This is the stability entry point: it exists so score variance across
    repeats can be produced and compared on demand, without re-running a whole
    rubric. It performs no aggregation and changes no reward.
    """
    _, _, _, reliability = _score_criterion_with_discipline(
        criterion, task_prompt, trajectory, model_for_call, api_base, api_key, n_trials
    )
    return reliability


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
        score, reason, err, reliability = _score_criterion_with_discipline(
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
            "reliability": reliability,
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
        "judge_reliability": {
            "discipline": "trinity/CRUCIBLE.md verifier principle 5a",
            "trials_per_criterion": _JUDGE_TRIALS_EFFECTIVE,
            "trials_floor": _JUDGE_TRIALS_FLOOR,
            "discipline_satisfied": _JUDGE_TRIALS_EFFECTIVE >= _JUDGE_TRIALS_FLOOR,
            "position_randomized": _JUDGE_TRIALS_EFFECTIVE > 1,
            "conformal_alpha": _CONFORMAL_ALPHA,
            "low_confidence_criteria": [
                r["id"]
                for r in results
                if (r.get("reliability", {}).get("conformal") or {}).get("low_confidence")
            ],
            "unstable_criteria": [
                r["id"]
                for r in results
                if (r.get("reliability", {}).get("stability") or {}).get("unstable")
            ],
            "note": (
                "The reported per-criterion score is the canonical trial: "
                "canonical section order, temperature 0.0, identical to what "
                "this judge produced before the discipline existed. Trials add "
                "reliability metadata beside the score and never rewrite it. A "
                "low-confidence or unstable criterion narrows how far its score "
                "should be trusted; it does not change the reward."
            ),
        },
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
