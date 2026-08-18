"""
services/scoring/rubric_weighted.py

Channel B of the weighted grader: judges a set of polarity-tagged rubric
criteria against a final response, then combines the per-criterion verdicts
with signed weights — mirroring weighted_judge.py's Channel A formula.

Deliberately does NOT import services/scoring/score_claims.py. It only needs
one capability from it — "judge one claim against one response, return a
coverage_outcome" — so that's expressed here as a duck-typed interface
instead of a hard import, keeping this module free of score_claims.py's
heavy import chain (matplotlib, aiohttp, dotenv) for callers that only want
to *combine* already-computed verdicts, or that supply a fake evaluator in
tests. In production, pass a real score_claims.CoverageEvaluator instance —
it already satisfies the interface:

    evaluator.evaluate_single_claim(claim: str, response: str) -> Awaitable[
        {"coverage_outcome": "fulfilled" | "partially_fulfilled" | "not_fulfilled", ...}
    ]

Rubric criterion shape (tests/rubric.json):

    [
      {"id": "claim_000", "text": "...", "weight": 1, "is_positive": true},
      {"id": "claim_001", "text": "...", "weight": 2, "is_positive": false}
    ]

`weight` is always a non-negative magnitude here — polarity is carried by
the explicit `is_positive` field, not the sign of the number. That's a
deliberate difference from Channel A's test_weights.json (where polarity
*is* the sign): a rubric criterion's LLM-judged verdict is inherently
graded, not boolean, so "how much of a violation occurred" needs its own
signed *magnitude* separate from "is this good or bad" — folding both into
one signed number would conflate them.

Legacy compatibility: a bare list of strings (score_claims.py's
extract_claims() output — today's GTFA_CLAIMS shape) is accepted too — each
string becomes a weight=1, is_positive=True goal criterion. This is what
lets a task with no rubric.json at all keep working unchanged.

Scoring formula, symmetric with weighted_judge.score_traj_tests():
    scale     = {"fulfilled": 1.0, "partially_fulfilled": 0.5, "not_fulfilled": 0.0}[outcome]
    pos_total = sum(|w| for goal criteria)
    earned    = sum(|w| * scale for goal criteria)
    penalty   = sum(|w| * scale for guard criteria)   # "fulfilled" == violation occurred
    value     = max(0, (earned - penalty) / pos_total)   if pos_total else None
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Protocol

_SCALE = {"fulfilled": 1.0, "partially_fulfilled": 0.5, "not_fulfilled": 0.0}


class ClaimEvaluator(Protocol):
    def evaluate_single_claim(self, claim: str, response: str) -> Awaitable[dict[str, Any]]: ...


@dataclass
class RubricCriterion:
    id: str
    text: str
    weight: float = 1.0
    is_positive: bool = True


def parse_rubric(raw: Any) -> list[RubricCriterion]:
    """Accepts either the legacy bare-string-list shape (score_claims.py's
    extract_claims() output) or the polarity-tagged object shape described
    in the module docstring."""
    if not raw:
        return []
    out: list[RubricCriterion] = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            out.append(RubricCriterion(id=f"claim_{i:03d}", text=item))
        elif isinstance(item, dict):
            text = item.get("text") or item.get("description") or item.get("title") or ""
            out.append(RubricCriterion(
                id=str(item.get("id", f"claim_{i:03d}")),
                text=text,
                weight=abs(float(item.get("weight", 1.0))),
                is_positive=bool(item.get("is_positive", True)),
            ))
    return out


async def evaluate_rubric(
    evaluator: ClaimEvaluator,
    criteria: list[RubricCriterion],
    response: str,
) -> dict[str, Any]:
    """Judge every criterion (one evaluator call each, run concurrently),
    then combine into one polarity-applied value in [0, 1] (or None if there
    are no goal criteria to normalize against)."""
    if not criteria:
        return {"value": None, "rows": []}

    results = await asyncio.gather(*[
        evaluator.evaluate_single_claim(c.text, response) for c in criteria
    ])

    rows: list[dict[str, Any]] = []
    pos_total = 0.0
    earned = 0.0
    penalty = 0.0
    for c, result in zip(criteria, results):
        outcome = result.get("coverage_outcome", "not_fulfilled")
        scale = _SCALE.get(outcome, 0.0)
        contribution = c.weight * scale
        if c.is_positive:
            pos_total += c.weight
            earned += contribution
            outcome_label = "credited" if scale >= 1.0 else ("partial_credit" if scale > 0 else "missed")
        else:
            penalty += contribution
            outcome_label = "penalized" if scale > 0 else "credited"
        rows.append({
            "id": c.id,
            "text": c.text,
            "weight": c.weight,
            "is_positive": c.is_positive,
            "coverage_outcome": outcome,
            "justification": result.get("justification", ""),
            "outcome": outcome_label,
        })

    value = max(0.0, (earned - penalty) / pos_total) if pos_total > 0 else None
    return {"value": value, "rows": rows}
