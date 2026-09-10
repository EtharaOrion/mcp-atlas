"""Grade the rubric channel BEFORE Harbor prints a number, not after.

WHY THIS EXISTS

Harbor prints its progress-bar metric and its end-of-job tables from whatever
reward each trial carried at trial exit: `print_job_results_tables(job_result)`
sits at harbor/cli/jobs.py:1416, straight after `job.run()` and before any
plugin is finalized. The container can only grade Channel A and the state
channel -- scripts/host_rubric_pass.py explains at length why the rubric cannot
be judged in there -- so the number on screen was the container's partial
reward. One measured trial printed

    Completion_Rate: 0.349 ... Reward 0.082

for a run the ledger credited with 40.0 once the rubric landed. Both numbers
were honest; only one of them was the run's.

Grading on TrialEvent.END closes the gap, because END still happens inside
`job.run()`:

  * `attach_job_plugin` awaits `on_job_start(job)` BEFORE `job.run()`
    (harbor/cli/job_plugins.py:32), so this hook registers after
    `Job._on_trial_completed` -- which has already put the rewards dict into
    `_live_rewards` -- and before `_update_metric_display` reads that dict for
    the bar. Mutating the dict IN PLACE is what makes the bar, the tables and
    result.json agree; rebinding `rewards` to a new dict would leave
    `_live_rewards` pointing at the ungraded one.
  * At job end Harbor rebuilds `final_rewards` from the trial results
    (harbor/job.py:765), so the summary tables, `reward_stats`, pass@k and the
    job's result.json all read the graded reward.

`Trial._finalize()` writes the trial's own result.json BEFORE emitting END
(harbor/trial/trial.py:331), so that file is rewritten here too. Without it a
resume would read the ungraded reward back out of disk
(`Job._maybe_init_existing_job` trusts the trial result, not the reward file).

THIS HOOK MUST NOT RAISE. `Trial._emit` awaits hooks with no try/except, so an
exception would kill a trial that has already finished its agent phase -- the
most expensive thing in the run. Every failure path here leaves the container's
reward in place and says so, which is exactly what the run_task.sh stage this
replaces does when the judge fails.

Attach it with:
    harbor run ... --plugin adapters.mcp_atlas.host_grade_plugin:HostGradePlugin \
                   --pk task=<task-dir>

scripts/run_task.sh passes that automatically (and PYTHONPATH=<repo>, since the
`harbor` console script puts its own bin dir on sys.path, not the cwd).

Env knobs:
    HOST_GRADE_OFF=1        do not grade in-process; leave it to run_task.sh
    HOST_GRADE_TASK=<dir>   task dir, when --pk task= is not given
    FORCE_HOST_RUBRIC=1     re-judge a trial that already carries a host grade
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from harbor.models.job.plugin import BaseJobPlugin
except Exception:  # pragma: no cover - importable outside a harbor env
    class BaseJobPlugin:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            pass

REPO = Path(__file__).resolve().parents[2]
GRADER = REPO / "scripts" / "host_rubric_pass.py"

# What Harbor is allowed to average. reward.json also carries provenance
# (`producer`, `unscored_reason`); feeding those to a metric would make Harbor
# try to compute a mean over a string.
REWARD_KEYS = ("reward", "completion_rate", "misbehave_rate")

# The ledger's own marker, written by host_rubric_pass.py. Its presence is how
# this plugin and stage_host_rubric each know the other already paid for a judge
# run -- the grade is a billed API call, so it must happen exactly once.
HOST_PRODUCER = "host_rubric_pass"


def _load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _python() -> str:
    venv = REPO / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else "python3"


def graded_rewards(reward_doc: dict | None) -> dict:
    """The metric fields of a reward.json, or {} when it graded nothing.

    A null component means "this channel produced no value", which is not the
    same fact as zero and must not reach a metric as one -- so nulls are
    dropped rather than coerced.
    """
    if not isinstance(reward_doc, dict):
        return {}
    return {k: reward_doc[k] for k in REWARD_KEYS
            if isinstance(reward_doc.get(k), (int, float))
            and not isinstance(reward_doc.get(k), bool)}


def apply_rewards(verifier_result, graded: dict) -> bool:
    """Update the trial's reward VALUES in place. True when something changed.

    In place, not reassigned: `Job._live_rewards` holds this same object and the
    progress bar reads it.

    THE KEY SET IS PRESERVED, and that is not cosmetic. Harbor averages a job by
    unioning the keys of every trial's dict and reading a key a trial LACKS as 0
    (metrics/base.py::aggregate_reward_dicts). So dropping a key here does not
    keep an unmeasured channel out of the mean -- it puts a 0 INTO the mean,
    inventing a measurement no run made and dragging down the average for every
    trial that did measure it:

        trial A {reward .4, completion_rate .9}   trial B {reward .6}
        -> Harbor reports completion_rate 0.45, from one real 0.9 and one
           fabricated 0.0.

    Clearing and refilling did exactly that whenever the grader produced a null
    component while a sibling trial graded cleanly. So now: a key the grader
    scored is overwritten with the graded value; a key it could not score keeps
    what the container measured. Both are numbers some grader really produced.
    Neither is invented.
    """
    if not graded or verifier_result is None:
        return False
    rewards = getattr(verifier_result, "rewards", None)
    if rewards is None:
        return False
    # Nothing established a shape yet, so there is none to preserve.
    if not rewards:
        rewards.update(graded)
        return True
    # Only keys the container already published. Adding one it never wrote is
    # the same 0-fill bug from the other side: this trial would carry a key its
    # siblings lack, and THEY would be the ones scored 0 for it.
    updated = {k: v for k, v in graded.items() if k in rewards}
    if not updated or all(rewards[k] == v for k, v in updated.items()):
        return False
    rewards.update(updated)
    return True


def patch_trial_result_file(result_path: Path, graded: dict) -> None:
    """Keep the on-disk trial result in step with the object in memory.

    Harbor wrote this file one line before it emitted END, so it still holds the
    container's reward; a resumed job reads rewards from here.
    """
    doc = _load(result_path)
    if not isinstance(doc, dict):
        return
    vres = doc.get("verifier_result")
    if not isinstance(vres, dict):
        return
    vres["rewards"] = graded
    tmp = result_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=4), encoding="utf-8")
    tmp.replace(result_path)


class HostGradePlugin(BaseJobPlugin):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__()
        self._task = str(kwargs.get("task") or os.environ.get("HOST_GRADE_TASK") or "")
        self._off = os.environ.get("HOST_GRADE_OFF", "0") == "1"
        self._job_dir: Path | None = None

    async def on_job_start(self, job) -> None:
        self._job_dir = Path(job.job_dir)
        if self._off:
            print("[host-grade] HOST_GRADE_OFF=1: leaving the rubric to run_task.sh")
            return
        # Registered here rather than in __init__ because this is the first
        # point a plugin is handed the Job. The registration ORDER is the whole
        # mechanism -- see the module docstring.
        job.on_trial_ended(self._on_trial_ended)

    async def on_job_end(self, job_result) -> None:
        return None

    async def _on_trial_ended(self, event) -> None:
        # Belt and braces around the one rule of this hook: never raise.
        try:
            await asyncio.to_thread(self._grade_trial, event)
        except Exception as exc:  # noqa: BLE001 - see module docstring
            print(f"[host-grade] {type(exc).__name__}: {exc} -- keeping the "
                  "container's reward", file=sys.stderr)

    def _grade_trial(self, event) -> None:
        if self._job_dir is None:
            return
        trial_dir = self._job_dir / event.trial_id
        reward_path = trial_dir / "verifier" / "reward.json"
        verifier_result = getattr(getattr(event, "result", None), "verifier_result", None)
        if verifier_result is None:
            # The trial died before verification; there is no reward to correct.
            return

        task = self._task or self._task_from_event(event)
        doc = _load(reward_path)
        already = isinstance(doc, dict) and doc.get("producer") == HOST_PRODUCER
        force = os.environ.get("FORCE_HOST_RUBRIC", "0") == "1"

        if not already or force:
            if not task:
                print("[host-grade] no task dir (pass --pk task=<dir>); "
                      "rubric stays ungraded", file=sys.stderr)
                return
            print(f"[host-grade] grading the rubric for {event.trial_id} "
                  "before Harbor reports it")
            proc = subprocess.run(
                [_python(), str(GRADER), "--trial", str(trial_dir), "--task", task],
                capture_output=True, text=True,
            )
            sys.stdout.write(proc.stdout)
            if proc.returncode != 0:
                sys.stderr.write(proc.stderr)
                print(f"[host-grade] grader exited {proc.returncode}; the rubric "
                      "channel stays UNSCORED and Harbor will report the "
                      "container's reward", file=sys.stderr)
                return
            doc = _load(reward_path)

        graded = graded_rewards(doc)
        if not graded:
            print(f"[host-grade] {event.trial_id}: reward.json carries no "
                  "gradeable value; keeping the container's reward", file=sys.stderr)
            return
        if apply_rewards(verifier_result, graded):
            # dict(...) of what was actually applied, not `graded`: the file and
            # the in-memory object must agree, or a resumed job reads back the
            # very shape apply_rewards just refused to write.
            patch_trial_result_file(trial_dir / "result.json",
                                    dict(verifier_result.rewards))
            print(f"[host-grade] {event.trial_id}: reward "
                  f"{graded.get('reward')} (graded) now what Harbor reports")

    @staticmethod
    def _task_from_event(event) -> str:
        """Task dir off the trial config, when --pk task= was not passed."""
        task = getattr(getattr(event, "config", None), "task", None)
        path = getattr(task, "path", None)
        return str(path) if path else ""
