"""
services/scoring/weighted_judge.py

Channel A of the weighted grader: runs a task's tests/test_outputs.py pytest
suite against one trajectory and scores it against tests/test_weights.json.

This module is Phase 1 of the "pytest + rubric" weighted-grading rollout.
Channel B (the rubric judge) and the top-level judge_weighted() ledger
combiner that merges Channel A + Channel B land in a later phase; today this
module only produces the `traj_tests` component value, so it's usable
standalone as soon as a task ships a tests/test_outputs.py + test_weights.json.

Guard-test polarity (read this before writing a test_weights.json):
    Every test in test_outputs.py is phrased positively — "X happened" — and
    whether X happening is good or bad is decided entirely by the *sign* of
    that test's weight here:
      * positive weight  -> a "goal" test. Passing earns credit.
      * negative weight  -> a "guard" test. Passing (the forbidden thing
        happened) earns a penalty; *not* triggering earns nothing (not a
        bonus) — a run that never goes near the guard shouldn't score higher
        than one that was never at risk of it.
    This is why nothing in traj_asserts.py is ever wrapped in `assert not
    ...` — the polarity belongs here, in the weights file, not in the test
    body. See traj_asserts.py's module docstring for the assertion API.

Scoring formula (mirrors complex-mcp's weighted grader):
    pos_total = sum(w for w in weights.values() if w > 0)
    earned    = sum(w for name, w in weights.items() if w > 0 and results[name])
    penalty   = sum(abs(w) for name, w in weights.items() if w < 0 and results[name])
    value     = max(0, (earned - penalty) / pos_total)   if pos_total else None

    `value is None` (no goal tests defined — a guard-only suite) means this
    component has no positive stake to normalize against, so it's dropped
    out of the top-level reward ledger entirely rather than counted as 0.

A task opts into Channel A by giving `components.traj_tests.weight` a
non-zero value in test_weights.json — a task with no test_weights.json (or a
flat legacy shape, see load_weights()) contributes nothing to the ledger,
so adding this module changes no existing task's score by default.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

_SCORING_DIR = Path(__file__).resolve().parent
if str(_SCORING_DIR) not in sys.path:
    sys.path.insert(0, str(_SCORING_DIR))

import traj_asserts  # noqa: E402

_ENV_VAR = traj_asserts._ENV_VAR  # "MCPATLAS_TRAJECTORY" — single source of truth


@dataclass
class ComponentWeight:
    weight: float = 0.0
    tests: dict[str, float] = field(default_factory=dict)


@dataclass
class Weights:
    threshold: float = 1.0
    traj_tests: ComponentWeight = field(default_factory=ComponentWeight)
    rubric: ComponentWeight = field(default_factory=ComponentWeight)


def load_weights(path: str | Path | None) -> Weights:
    """Load tests/test_weights.json. Two accepted shapes:

    Flat (legacy/simple) — a bare mapping of test name -> signed weight.
    This populates traj_tests.tests but leaves traj_tests.weight at 0, so a
    task doesn't silently start contributing to the ledger just by having a
    test_weights.json file — a task author must opt in explicitly with the
    component shape below.

        {"test_used_search_tool": 1, "test_called_forbidden_tool": -2}

    Component (full) shape:

        {
          "threshold": 1.0,
          "components": {
            "traj_tests": {"weight": 3, "tests": {"test_x": 1, "test_y": -2}},
            "rubric":     {"weight": 5}
          }
        }

    A missing file returns all-zero weights (traj_tests inert, nothing
    changes vs. today's grading).
    """
    if path is None:
        return Weights()
    p = Path(path)
    if not p.exists():
        return Weights()
    data = json.loads(p.read_text(encoding="utf-8"))

    if "components" not in data and "threshold" not in data:
        # flat shape: bare {test_name: weight}
        return Weights(traj_tests=ComponentWeight(weight=0.0, tests=dict(data)))

    components = data.get("components", {})
    traj_raw = components.get("traj_tests", {})
    rubric_raw = components.get("rubric", {})
    return Weights(
        threshold=float(data.get("threshold", 1.0)),
        traj_tests=ComponentWeight(
            weight=float(traj_raw.get("weight", 0.0)),
            tests=dict(traj_raw.get("tests", {})),
        ),
        rubric=ComponentWeight(weight=float(rubric_raw.get("weight", 0.0))),
    )


class _Collector:
    """pytest plugin: records pass/fail per test function, ignoring
    setup/teardown-only phases unless they themselves failed (a fixture
    error means the test's body never ran, which counts as a fail)."""

    def __init__(self) -> None:
        self.results: dict[str, bool] = {}

    def pytest_runtest_logreport(self, report: Any) -> None:
        name = report.nodeid.rsplit("::", 1)[-1]
        if report.when == "call":
            self.results[name] = report.outcome == "passed"
        elif report.when in ("setup", "teardown") and report.outcome == "failed":
            self.results[name] = False


def _purge_module_cache(test_file: Path) -> None:
    """Drop any previously-imported module backed by this exact file, so a
    task's test_outputs.py doesn't leak module-level state (or stale
    trajectory data) across repeated grading calls in the same process."""
    test_file = test_file.resolve()
    stale = [
        name for name, mod in list(sys.modules.items())
        if getattr(mod, "__file__", None) and Path(mod.__file__).resolve() == test_file
    ]
    for name in stale:
        del sys.modules[name]


def _run_traj_pytest(trajectory: dict | list, test_file: str | Path) -> dict[str, bool]:
    """Run `test_file` under pytest against `trajectory`, return
    {test_function_name: passed}. Stages `trajectory` to a temp JSON file and
    points MCPATLAS_TRAJECTORY at it for the duration of the run only."""
    test_file = Path(test_file)
    if not test_file.exists():
        return {}

    traj_asserts.reset_cache()
    _purge_module_cache(test_file)

    fd, tmp_path = tempfile.mkstemp(prefix="mcpatlas-traj-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(trajectory, f)

        prev = os.environ.get(_ENV_VAR)
        os.environ[_ENV_VAR] = tmp_path
        try:
            collector = _Collector()
            pytest.main(
                [str(test_file), "-q", "-p", "no:cacheprovider", "--import-mode=importlib"],
                plugins=[collector],
            )
            return dict(collector.results)
        finally:
            if prev is None:
                os.environ.pop(_ENV_VAR, None)
            else:
                os.environ[_ENV_VAR] = prev
            traj_asserts.reset_cache()
            _purge_module_cache(test_file)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def traj_test_rows(results: dict[str, bool], weights: dict[str, float]) -> list[dict[str, Any]]:
    """One row per weighted test, for downstream reporting (ctrf.json /
    detail.json). `outcome` is the *polarity-applied* verdict — "credited"
    for a passing goal or a non-triggering guard, "penalized" for a
    triggering guard, "missed" for a failing goal, "not_run" if the test
    wasn't collected (e.g. it errored at collection time)."""
    rows: list[dict[str, Any]] = []
    for name, weight in weights.items():
        raw = results.get(name)
        if raw is None:
            outcome = "not_run"
        elif weight >= 0:
            outcome = "credited" if raw else "missed"
        else:
            outcome = "penalized" if raw else "credited"
        rows.append({
            "name": name,
            "weight": weight,
            "raw_passed": raw,
            "outcome": outcome,
        })
    return rows


def score_traj_tests(results: dict[str, bool], weights: dict[str, float]) -> float | None:
    """Combine per-test pass/fail with signed weights into one value in
    [0, 1], or None if there are no goal (positive-weight) tests to
    normalize against — see the module docstring."""
    pos_total = sum(w for w in weights.values() if w > 0)
    if pos_total <= 0:
        return None
    earned = sum(w for name, w in weights.items() if w > 0 and results.get(name))
    penalty = sum(abs(w) for name, w in weights.items() if w < 0 and results.get(name))
    return max(0.0, (earned - penalty) / pos_total)


def score_task(
    trajectory: dict | list,
    test_file: str | Path,
    weights_file: str | Path | None,
) -> dict[str, Any]:
    """Convenience end-to-end entry point for one task: load weights, run
    the pytest suite, score it. Returns a dict with `value` (float|None),
    `weight` (this component's ledger weight — 0 unless the task's
    test_weights.json opts in), and `rows` (per-test detail for reporting)."""
    weights = load_weights(weights_file)
    results = _run_traj_pytest(trajectory, test_file)
    value = score_traj_tests(results, weights.traj_tests.tests)
    return {
        "value": value,
        "weight": weights.traj_tests.weight,
        "rows": traj_test_rows(results, weights.traj_tests.tests),
    }


# ============================================================================
# Phase 3: reward ledger combiner + verifier artifact writer
# ============================================================================
#
# mcp-atlas's ledger has two components — traj_tests (Channel A) and rubric
# (Channel B) — not complex-mcp's full five (state_completion/state_misbehave/
# graph_plan/traj_tests/rubric). There's no world-state-diff channel here, so
# state_completion/state_misbehave/graph_plan don't apply and aren't
# implemented. Both implemented components already fold their own internal
# goal/guard polarity into a single "goodness" value in [0, 1] (see
# score_traj_tests() and rubric_weighted.evaluate_rubric()), so unlike
# complex-mcp's ledger, combining them at the top level is a plain weighted
# average, not a further earned/penalty split.


def combine_ledger(ledger: dict[str, dict[str, Any]]) -> float | None:
    """Combine component values into one reward in [0, 1].

    `ledger` maps component name -> {"weight": float, "value": float|None}.
    A component only counts if its weight is > 0 and its value isn't None
    (None means "no goal tests/criteria defined" — see score_traj_tests()/
    evaluate_rubric() — so there's nothing to weigh in for that component).

    Returns None if no component is active — the caller should fall back to
    whatever the pipeline's default (unweighted) scoring already does rather
    than treating an all-inert ledger as a reward of 0.
    """
    active = {
        name: c for name, c in ledger.items()
        if c.get("weight", 0) > 0 and c.get("value") is not None
    }
    if not active:
        return None
    total_weight = sum(c["weight"] for c in active.values())
    return sum(c["weight"] * c["value"] for c in active.values()) / total_weight


def judge_weighted(
    *,
    trajectory: dict | list | None = None,
    test_file: str | Path | None = None,
    test_weights_file: str | Path | None = None,
    traj_results: dict[str, bool] | None = None,
    rubric_value: float | None = None,
    rubric_weight: float = 0.0,
    rubric_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Top-level combiner for one task's grading run.

    Channel A is computed here directly (given trajectory + test_file +
    test_weights_file), since it's synchronous and self-contained. Channel B
    is async (it makes LLM-judge calls via rubric_weighted.evaluate_rubric)
    so its already-computed `value`/`weight`/`rows` are passed in instead of
    computed here — callers `await evaluate_rubric(...)` first, then pass the
    result through. Pass `traj_results` directly (skipping the pytest run)
    if you've already run it, e.g. from a caller that also wants the raw
    per-test dict for other purposes.

    Returns {"reward": float|None, "ledger": {...}, "traj_test_rows": [...],
    "rubric_rows": [...]}. `reward` is None only if neither channel is
    active for this task (see combine_ledger()) — callers should treat that
    as "this task isn't opted into weighted grading" and fall back to
    whatever default scoring the pipeline already does.
    """
    weights = load_weights(test_weights_file) if test_weights_file else Weights()
    ledger: dict[str, dict[str, Any]] = {}
    rows_traj: list[dict[str, Any]] = []

    if weights.traj_tests.weight and (traj_results is not None or (trajectory is not None and test_file)):
        results = traj_results if traj_results is not None else _run_traj_pytest(trajectory, test_file)
        value = score_traj_tests(results, weights.traj_tests.tests)
        rows_traj = traj_test_rows(results, weights.traj_tests.tests)
        if value is not None:
            ledger["traj_tests"] = {"weight": weights.traj_tests.weight, "value": value}

    effective_rubric_weight = rubric_weight or weights.rubric.weight
    if effective_rubric_weight and rubric_value is not None:
        ledger["rubric"] = {"weight": effective_rubric_weight, "value": rubric_value}

    reward = combine_ledger(ledger)
    return {
        "reward": reward,
        "ledger": ledger,
        "traj_test_rows": rows_traj,
        "rubric_rows": rubric_rows or [],
    }


def _ctrf_report(traj_test_rows: list[dict[str, Any]], tool_name: str = "mcp-atlas-weighted-judge") -> dict[str, Any]:
    """Render Channel A's per-test rows as a CTRF (Common Test Report Format)
    document. A row's `outcome` (already polarity-applied — "credited" /
    "penalized" / "missed" / "not_run") maps to CTRF status: "credited" ->
    passed, everything else -> failed/skipped, so CTRF readers see pass/fail
    from the *grading* perspective, not raw pytest pass/fail."""
    now_ms = int(time.time() * 1000)
    tests = []
    passed = failed = skipped = 0
    for row in traj_test_rows:
        if row["outcome"] == "not_run":
            status = "skipped"
            skipped += 1
        elif row["outcome"] == "credited":
            status = "passed"
            passed += 1
        else:
            status = "failed"
            failed += 1
        tests.append({
            "name": row["name"],
            "status": status,
            "duration": 0,
            "extra": {"weight": row["weight"], "raw_passed": row["raw_passed"], "outcome": row["outcome"]},
        })
    return {
        "results": {
            "tool": {"name": tool_name},
            "summary": {
                "tests": len(tests),
                "passed": passed,
                "failed": failed,
                "pending": 0,
                "skipped": skipped,
                "other": 0,
                "start": now_ms,
                "stop": now_ms,
            },
            "tests": tests,
        }
    }


def write_verifier_artifacts(out_dir: str | Path, result: dict[str, Any]) -> None:
    """Write Harbor's expected verifier/ artifact set from a judge_weighted()
    result: reward.json (Harbor's VerifierResult shape, {"reward": float}),
    reward.txt (the same value as plain text), ctrf.json (Channel A's
    per-test results in CTRF format), and detail.json (the full breakdown —
    ledger + both channels' per-item rows — for debugging, not read by
    Harbor). Mirrors tests/agent_judge.py's existing reward.json/reward.txt
    convention exactly, so a task's verifier output is drop-in compatible
    whether it comes from agent_judge.py or this weighted judge.

    A None reward (no component active) is written as 0.0 — a task that
    opted into weighted grading but has nothing scoreable shouldn't emit an
    invalid/missing reward file.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    reward = result.get("reward")
    reward_value = reward if reward is not None else 0.0
    (out_dir / "reward.txt").write_text(str(reward_value))
    (out_dir / "reward.json").write_text(json.dumps({"reward": reward_value}, indent=2))
    (out_dir / "ctrf.json").write_text(json.dumps(_ctrf_report(result.get("traj_test_rows", [])), indent=2))
    (out_dir / "detail.json").write_text(json.dumps(result, indent=2))
