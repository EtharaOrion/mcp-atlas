"""A trial that was never graded must not be published as a trial that scored 0.

Three bugs, all one root mistake -- `d.get(key, default)` does not apply the
default when the key is PRESENT and NULL, which is exactly how Harbor records a
trial that died before the verify phase (docker compose failure, rate limit):

  1. host_rubric_pass._sync_harbor_result raised AttributeError on
     `d.get("verifier_result", {}).get("rewards")`, so the one record that most
     needed correcting -- a crashed trial's stale reward -- was the one record
     the sync always failed to touch.
  2. make_delivery divided `report.get("rubric_weights_percentage", 0)` by 100
     and got TypeError, taking down the whole delivery step.
  3. harbor_to_output folded the unscored trials' placeholder 0 into the reward
     mean, so a job where 3 of 4 trials never produced a trajectory reported a
     confident mean instead of saying three runs went ungraded.

The observed failure: 4 trials, 1 graded at 0.1724, 3 dead before verify. The
pipeline printed "mean reward 4.31" -- 17.24/4 -- reporting infrastructure
failures as agent failures, then crashed on the delivery bundle.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hrp = _load_module("host_rubric_pass")
mkd = _load_module("make_delivery")
h2o = _load_module("harbor_to_output")


# --------------------------------------------------------------------------
# 1. the rubric CLI's result.json sync
# --------------------------------------------------------------------------

def _trial(tmp_path: Path, trial_doc, job_doc) -> Path:
    trial = tmp_path / "job" / "trial"
    trial.mkdir(parents=True)
    (trial / "result.json").write_text(json.dumps(trial_doc))
    (trial.parent / "result.json").write_text(json.dumps(job_doc))
    return trial


def test_sync_survives_null_verifier_result(tmp_path, capsys):
    """The crashed-trial shape Harbor actually writes: keys present, values null."""
    trial = _trial(tmp_path, {"verifier_result": None}, {"stats": None})

    hrp._sync_harbor_result(trial, 0.1724)

    err = capsys.readouterr().err
    assert "could not sync" not in err, f"sync still raising: {err}"


def test_sync_does_not_claim_a_write_it_did_not_make(tmp_path, capsys):
    trial = _trial(tmp_path, {"verifier_result": None}, {"stats": None})

    hrp._sync_harbor_result(trial, 0.1724)

    out = capsys.readouterr().out
    assert "nothing to sync" in out
    assert "synced" not in out, "reported a sync of a document it never wrote"


def test_sync_still_rewrites_a_real_verifier_result(tmp_path):
    """The null guards must not cost the sync its actual job."""
    trial = _trial(
        tmp_path,
        {"verifier_result": {"rewards": {"reward": 0.0}}},
        {"stats": {"evals": {"e1": {"metrics": [{"reward": 0.0}, {"reward": 0.0}]}}}},
    )

    hrp._sync_harbor_result(trial, 0.1724)

    assert json.loads((trial / "result.json").read_text()) \
        ["verifier_result"]["rewards"]["reward"] == 0.1724
    metrics = json.loads((trial.parent / "result.json").read_text()) \
        ["stats"]["evals"]["e1"]["metrics"]
    assert [m["reward"] for m in metrics] == [0.1724, 0.1724]


# --------------------------------------------------------------------------
# 2. the delivery bundle
# --------------------------------------------------------------------------

def _output_dir(tmp_path: Path, reports: list[dict]) -> Path:
    src = tmp_path / "output" / "demo"
    (src / "trajectory").mkdir(parents=True)
    (src / "pass_summary.json").write_text(
        json.dumps({"model": "claude-opus-5", "per_run": []})
    )
    for i, report in enumerate(reports, 1):
        run = src / "trajectory" / f"run_{i}"
        run.mkdir()
        (run / "report.json").write_text(json.dumps(report))
    return src


def _report(rubric_pct):
    return {"model": "claude-opus-5", "run_index": 1,
            "rubric_weights_percentage": rubric_pct, "rubric": []}


def test_delivery_survives_ungraded_rubric_channel(tmp_path):
    """`.get(key, 0)` returned None here and the division took down delivery."""
    src = _output_dir(tmp_path, [_report(None)])

    mkd.make_delivery("demo", tmp_path / "output", tmp_path / "tasks",
                      tmp_path / "delivery")

    score = json.loads(
        (tmp_path / "delivery" / "demo" / "trajectory" / "opus.5" / "run 1"
         / "verifier" / "score.json").read_text())
    assert score["reward"] is None, "published a scored 0 for an ungraded run"
    assert score["scored"] is False
    assert score["rubric_weights_percentage"] is None


def test_delivery_still_scores_a_graded_run(tmp_path):
    src = _output_dir(tmp_path, [_report(17.24)])

    mkd.make_delivery("demo", tmp_path / "output", tmp_path / "tasks",
                      tmp_path / "delivery")

    score = json.loads(
        (tmp_path / "delivery" / "demo" / "trajectory" / "opus.5" / "run 1"
         / "verifier" / "score.json").read_text())
    assert score["reward"] == 0.1724
    assert score["scored"] is True


# --------------------------------------------------------------------------
# 3. the reward mean
# --------------------------------------------------------------------------

def _job(tmp_path: Path, rewards: list[dict]) -> tuple[Path, Path]:
    """A Harbor job whose trials carry the given verifier/reward.json docs."""
    job = tmp_path / "job"
    job.mkdir()
    (job / "config.json").write_text(
        json.dumps({"agents": [{"name": "claude-code", "model_name": "claude-opus-5"}]})
    )
    (job / "result.json").write_text(json.dumps(
        {"id": "job-1",
         "stats": {"evals": {"e1": {"metrics": [{} for _ in rewards]}}}}))
    for i, rw in enumerate(rewards):
        trial = job / f"trial_{i}"
        (trial / "verifier").mkdir(parents=True)
        (trial / "config.json").write_text(
            json.dumps({"task": {"path": "tasks/demo", "name": "demo"}}))
        (trial / "result.json").write_text(json.dumps({"reward": 0.0}))
        (trial / "verifier" / "reward.json").write_text(json.dumps(rw))
    out = tmp_path / "out"
    out.mkdir()
    return job, out


GRADED = {"reward": 0.1724, "producer": "host_rubric_pass"}
UNGRADED = {"reward": 0.0}  # no producer -> harbor_to_output marks it unscored


def test_ungraded_trials_stay_out_of_the_reward_mean(tmp_path):
    """The reported case: 1 graded at 0.1724 plus 3 that never ran."""
    job, out = _job(tmp_path, [GRADED, UNGRADED, UNGRADED, UNGRADED])

    task = h2o.convert_job(job, out, ks=[], run_offset=0)[0]
    metrics = json.loads((task / "summary.json").read_text())["metrics"]

    assert metrics["runs_unscored"] == 3
    # 17.24, not 17.24/4 == 4.31.
    assert metrics["avg_reward"] == 17.24


def test_a_wholly_ungraded_job_reports_no_mean_rather_than_zero(tmp_path):
    job, out = _job(tmp_path, [UNGRADED, UNGRADED])

    task = h2o.convert_job(job, out, ks=[], run_offset=0)[0]
    metrics = json.loads((task / "summary.json").read_text())["metrics"]

    assert metrics["avg_reward"] is None, "unmeasured published as a scored 0.0"
    assert metrics["runs_unscored"] == 2


def test_every_attempt_still_counts_toward_the_episode_total(tmp_path):
    """Excluding a crash from the MEAN must not erase it from the record."""
    job, out = _job(tmp_path, [GRADED, UNGRADED, UNGRADED, UNGRADED])

    task = h2o.convert_job(job, out, ks=[], run_offset=0)[0]
    summary = json.loads((task / "summary.json").read_text())

    assert summary["config"]["episodes"] == 4
    assert len(summary["episodes"]) == 4
    assert [e["scored"] for e in summary["episodes"]] == [True, False, False, False]
