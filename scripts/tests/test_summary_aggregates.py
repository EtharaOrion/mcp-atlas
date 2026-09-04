"""summary.json aggregates must reconcile with result.json's per-trial metrics.

The bug these guard: avg_completion_rate averaged the host-side traj_tests
value, on the assumption that result.json's per-trial completion_rate carried
the same quantity. It does not -- that field is the container's Rc (the
unweighted fraction of positive checks passed, written by the bundle's
test_write_reward_json), while traj_tests is a weight-normalised score. The two
never reconciled, and once traj_tests went unmeasured the rollup published 0.0
next to per-trial records of 0.9 and 0.714: the summary said the runs completed
nothing while the records beside it said otherwise.

Nothing else in the suite exercises the aggregation, so these are the only
tests standing between that bug and a repeat.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "harbor_to_output", _SCRIPTS / "harbor_to_output.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


h2o = _load_module()


def _build_job(
    tmp_path: Path, per_trial: list[dict], trial_reward: dict | None = None
) -> tuple[Path, Path]:
    """A minimal Harbor job dir carrying `per_trial` metrics in result.json.

    `trial_reward`, when given, is written as each trial's verifier/reward.json --
    the container-side record the reshaper reads to derive the final reward.
    """
    job = tmp_path / "job"
    job.mkdir()
    (job / "config.json").write_text(
        json.dumps({"agents": [{"name": "claude-code", "model_name": "claude-opus-5"}]})
    )
    (job / "result.json").write_text(
        json.dumps({"id": "job-1", "stats": {"evals": {"e1": {"metrics": per_trial}}}})
    )
    for i in range(len(per_trial)):
        trial = job / f"trial_{i}"
        trial.mkdir()
        (trial / "config.json").write_text(
            json.dumps({"task": {"path": "tasks/demo", "name": "demo"}})
        )
        (trial / "result.json").write_text(json.dumps({"reward": 0.0}))
        if trial_reward is not None:
            verifier = trial / "verifier"
            verifier.mkdir()
            # harbor_to_output refuses a reward.json whose producer it does not
            # recognise, so a fixture omitting the field is rejected before any
            # aggregate is computed. Default it; a test may still pin its own.
            trial_reward = {"producer": "host_rubric_pass", **trial_reward}
            (verifier / "reward.json").write_text(json.dumps(trial_reward))
    out = tmp_path / "out"
    out.mkdir()
    return job, out


def _convert(tmp_path: Path, per_trial: list[dict]) -> tuple[dict, list[dict]]:
    job, out = _build_job(tmp_path, per_trial, {"reward": 0.0, "scored": True})
    written = h2o.convert_job(job, out, ks=[], run_offset=0)
    assert written, "convert_job produced no task output"
    task = written[0]
    summary = json.loads((task / "summary.json").read_text())
    result = json.loads((task / "result.json").read_text())
    recorded: list[dict] = []
    for eval_data in ((result.get("stats") or {}).get("evals") or {}).values():
        recorded.extend(eval_data.get("metrics") or [])
    return summary, recorded


@pytest.mark.parametrize(
    "aggregate,component",
    [("avg_completion_rate", "completion_rate"), ("avg_misbehave_rate", "misbehave_rate")],
)
def test_aggregate_reconciles_with_per_trial_metrics(tmp_path, aggregate, component):
    """The aggregate equals the mean of the values it summarises.

    This is the property the audit re-derives (crucible rollout.py,
    REWARD-COMPONENT-NOT-REDERIVABLE), computed the same way: over the trials
    that actually recorded the component.
    """
    summary, recorded = _convert(
        tmp_path,
        [
            {"completion_rate": 0.9, "misbehave_rate": 0.0, "reward": 0.0, "scored": 1.0},
            {"completion_rate": 0.5, "misbehave_rate": 0.25, "reward": 0.0, "scored": 1.0},
        ],
    )
    values = [m[component] for m in recorded if component in m]
    rederived = sum(values) / len(values)
    reported = summary["metrics"][aggregate]
    assert reported is not None, f"{aggregate} reported as unmeasured despite recorded values"
    assert abs(float(reported) - rederived) <= 1e-6


def test_aggregate_ignores_trials_missing_the_component(tmp_path):
    """A trial that recorded no completion_rate is skipped, not counted as zero.

    Averaging it in as 0.0 would drag the aggregate below what the audit
    re-derives, which skips absent components -- and would understate a run.
    """
    summary, recorded = _convert(
        tmp_path,
        [{"completion_rate": 0.8, "misbehave_rate": 0.0, "reward": 0.0}, {"reward": 0.0}],
    )
    assert summary["metrics"]["avg_completion_rate"] == pytest.approx(0.8)


def test_unmeasured_channel_reports_null_not_zero(tmp_path):
    """An unmeasured Channel A must not be published as a scored 0.0.

    A component that produced no value and one that scored zero are different
    facts; collapsing them is the confusion the reward ledger already refuses.
    """
    summary, _ = _convert(
        tmp_path, [{"completion_rate": 0.9, "misbehave_rate": 0.0, "reward": 0.0}]
    )
    assert summary["metrics"]["avg_traj_tests"] is None


def _convert_with_trial_reward(tmp_path: Path, trial_reward: dict) -> dict:
    """Reshape one trial carrying `trial_reward`, returning its run_1 detail.json."""
    job, out = _build_job(
        tmp_path, [{"completion_rate": 0.9, "misbehave_rate": 0.0, "reward": 0.0}], trial_reward
    )
    written = h2o.convert_job(job, out, ks=[], run_offset=0)
    assert written
    return json.loads((written[0] / "trajectory" / "run_1" / "verifier" / "detail.json").read_text())


def test_scored_zero_records_a_machine_readable_reason(tmp_path):
    """A zero reward must carry why, or it is indistinguishable from a crash.

    The bundle's test.sh records a reason only when Channel A never wrote. A
    *scored* zero -- suite ran, run earned nothing -- previously arrived with no
    explanation, which is what VER-UNATTRIBUTED-ZERO fires on.
    """
    detail = _convert_with_trial_reward(
        tmp_path, {"reward": 0.0, "completion_rate": 0.9, "misbehave_rate": 0.0, "scored": True}
    )
    assert detail.get("zero_reason"), "a scored zero reached detail.json with no recorded cause"


def test_container_supplied_zero_reason_is_not_overwritten(tmp_path):
    """The container knows why it failed; this layer does not. Carry it through."""
    supplied = "unscored: reward_channel_a.json was never written"
    detail = _convert_with_trial_reward(
        tmp_path,
        {"reward": 0.0, "completion_rate": 0.0, "misbehave_rate": 0.0,
         "scored": False, "zero_reason": supplied},
    )
    assert detail["zero_reason"] == supplied


def test_nonzero_reward_carries_no_zero_reason(tmp_path):
    """Only a zero needs explaining; a scored run must not gain a spurious field."""
    detail = _convert_with_trial_reward(
        tmp_path, {"reward": 0.75, "completion_rate": 0.9, "misbehave_rate": 0.0, "scored": True}
    )
    assert "zero_reason" not in detail


def test_mean_or_none_distinguishes_unmeasured_from_zero():
    assert h2o._mean_or_none([]) is None
    assert h2o._mean_or_none([None, None]) is None
    assert h2o._mean_or_none([0.0]) == 0.0
    assert h2o._mean_or_none([0.9, 0.5]) == pytest.approx(0.7)
    # The old helper's behaviour, kept for counts where zero is the truth.
    assert h2o._mean([]) == 0.0


def test_report_renders_unmeasured_without_crashing():
    assert h2o._fmt_metric(None) == "unmeasured"
    assert h2o._fmt_metric(0.5) == "0.5000"
