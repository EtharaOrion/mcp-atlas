#!/usr/bin/env python3
"""Grade a finished trial's rubric channel on the HOST, then recompute reward.

WHY THIS EXISTS

`tests/test.sh` grades every channel inside the task container. That works for
Channel A and the state channel, which need the live light-servers the agent
wrote to. It does not work for the rubric channel when the judge is codex:
python:3.12-slim has no `codex` binary, and the only way to put a working one
there is to mount the operator's ChatGPT credential into a container that just
ran an agent under --permission-mode=bypassPermissions. Harbor's verifier
cannot be isolated from that container either -- environment_mode='separate'
brings up "a fresh copy of the top-level [environment]", which restarts
light-servers clean and destroys the world the state channel exists to read.

So the rubric is graded here instead, on the host, where codex is already
installed and logged in and the credential never leaves the machine it belongs
to. The container keeps grading everything that needs the live world.

WHAT IT RECOMPUTES, AND WHY IT CANNOT JUST PATCH THE NUMBER

test_outputs.py accumulates the denominator only over components it actually
scored (`den += w` sits after the `v is None` guard). An unscored rubric is
therefore excluded from the divisor rather than counted as zero, so folding a
rubric score in afterwards changes both halves of the fraction. The ledger math
below mirrors test_outputs.py exactly for that reason -- including the gates,
which can zero a reward that the arithmetic alone would leave positive.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools" / "delivery"))
from harbor_to_output import fmt_reward, norm_reward  # noqa: E402

sys.path.insert(0, str(REPO / "services" / "scoring"))

import agent_log_to_trajectory as alt  # noqa: E402


def _load(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def recompute_reward(weights: dict, chan_a, rubric_value, rc_val, rb_val,
                     guards_tripped: list) -> tuple[float, dict]:
    """The ledger from test_outputs.py, kept line-for-line equivalent."""
    comps = weights.get("components") or {}
    values = {"traj_tests": chan_a, "rubric": rubric_value,
              "state_completion": rc_val}
    num, den, ledger = 0.0, 0.0, {}
    for name, spec in comps.items():
        spec = spec or {}
        w = spec.get("weight") or 0
        if name == "state_misbehave":
            continue
        if not spec.get("graded") or w <= 0:
            ledger[name] = {"status": "retired", "weight": w, "value": None}
            continue
        v = values.get(name)
        if v is None:
            ledger[name] = {"status": "unscored", "weight": w, "value": None}
            continue
        # `value` is what the ledger publishes; the arithmetic below stays on
        # the full float. Cutting only the published copy keeps the report
        # readable at the tree's two places without the reward inheriting a
        # truncation on every component it sums.
        ledger[name] = {"status": "scored", "weight": w, "value": norm_reward(float(v))}
        num += w * float(v)
        den += w

    mis = comps.get("state_misbehave") or {}
    mis_w = mis.get("weight") or 0
    if mis.get("graded") and mis_w < 0 and rb_val is not None:
        num -= abs(mis_w) * float(rb_val)
        ledger["state_misbehave"] = {"status": "scored", "weight": mis_w,
                                     "severity": norm_reward(float(rb_val))}
    else:
        ledger["state_misbehave"] = {
            "status": "retired" if not mis.get("graded") else "unscored",
            "weight": mis_w, "severity": None}

    reward = norm_reward(max(0.0, num / den)) if den else 0.0

    gate = weights.get("gate") or {}
    if gate.get("require_state_exact") and rc_val is not None \
            and (rc_val < 1.0 or (rb_val or 0) > 0):
        reward = 0.0
    if gate.get("require_no_guards") and guards_tripped:
        reward = 0.0
    floor = gate.get("floor")
    if floor is not None and reward < float(floor):
        reward = 0.0
    return reward, ledger


def _sync_harbor_result(trial: Path, reward: float) -> None:
    """Rewrite the stale reward Harbor recorded before the host pass ran.

    Harbor finalises its own result.json at the end of the verify phase, which
    is necessarily before this pass grades the rubric. Both the trial-level and
    job-level records therefore hold the pre-rubric number. Best-effort: a
    stale summary is bad, but it is not worth failing a graded run over.
    """
    for path, mutate in (
        (trial / "result.json", lambda d: (d.get("verifier_result") or {}).get("rewards")),
        (trial.parent / "result.json", None),
    ):
        try:
            if not path.exists():
                continue
            doc = json.loads(path.read_text())
            touched = 0
            if mutate is not None:
                rewards = mutate(doc)
                if isinstance(rewards, dict):
                    rewards["reward"] = reward
                    touched += 1
            else:
                for ev in ((doc.get("stats") or {}).get("evals") or {}).values():
                    for metric in ev.get("metrics") or []:
                        if isinstance(metric, dict) and "reward" in metric:
                            metric["reward"] = reward
                            touched += 1
                    # reward_stats buckets trial names under the reward as a
                    # STRING KEY, so a stale entry here is a second, contradictory
                    # copy of the score in the same file -- and it kept the raw
                    # float even after metrics[] was synced. Re-key only this
                    # trial's entry; sibling trials own their own buckets.
                    rstats = (ev.get("reward_stats") or {}).get("reward")
                    if isinstance(rstats, dict):
                        for key in list(rstats):
                            rest = [t for t in rstats[key] if t != trial.name]
                            if len(rest) != len(rstats[key]):
                                if rest:
                                    rstats[key] = rest
                                else:
                                    del rstats[key]
                                rstats.setdefault(str(reward), []).append(trial.name)
                                touched += 1
            if not touched:
                # No reward field exists to correct -- the trial died before the
                # verify phase, so there is no stale number here. Say that
                # instead of printing "synced", which claimed a write that never
                # happened. The graded reward still lives in verifier/reward.json,
                # which is what the output pipeline actually reads.
                print(f"[host-rubric] nothing to sync in {path.name} "
                      "(no verifier reward recorded); reward.json remains the source")
                continue
            path.write_text(json.dumps(doc, indent=4))
            print(f"[host-rubric] synced {path.name} -> {fmt_reward(reward)} ({touched} field(s))")
        except (OSError, ValueError, AttributeError) as exc:
            print(f"[host-rubric] could not sync {path}: {exc!r}", file=sys.stderr)


# --- judge transport ---------------------------------------------------------
# The judge runs in its OWN container by default (services/rubric-judge/):
# not on the host, and not in the verifier.
#
# It is off the HOST because the host is the one place a scoring step should not
# run. `codex exec` there inherits the operator's PATH, network and entire
# ~/.codex -- 378 MB of session history plus a config.toml registering an MCP
# server at a path no other machine has. None of that belongs in a grading path
# and none of it reproduces anywhere else.
#
# It is not folded into the VERIFIER container because that one carries the
# whole grading tree and each bundle's baked /tests. The judge needs neither, so
# putting the credential there would widen its blast radius for nothing.
#
# Verified 2026-09-10 against run_47: 17/17 criteria identical to the host pass,
# same rubric_passed. `codex exec --sandbox read-only` needs no modification
# inside the container.
# ---------------------------------------------------------------------------
# Phase 2 re-entry: run the verifier again against a trial that already exists.
#
# Harbor drives agent -> verifier inside one `harbor run`, and offers no way back
# in: `harbor job resume` deletes the whole trial directory (cli/jobs.py:1594)
# and re-runs it from the agent, which is the expensive half and the half that
# was already fine. So a trial that graded badly because the EVAL image was
# wrong, or test_outputs.py had a bug, costs a full agent re-run to re-grade.
#
# In separate mode it does not have to. The collect hook writes the world
# snapshot and the trajectory to artifacts/_atlas/ before teardown, and
# tests/test.sh opens by restoring them, so Phase 2 already reads frozen files
# and never touches the agent's containers. Everything it needs is on disk.
#
# What this does, then, is rebuild the Trial object from the trial's own
# config.json and call the verifier phase alone.
#
# It rides on Harbor private API (`_run_verifier`, `_run_separate_verifier`,
# `_result`). There is no public equivalent -- `harbor trial start` runs
# everything -- so an upgrade can break this. patch_harbor.py already couples us
# to Harbor internals, so the exposure is not new, but it is real: if Harbor
# moves, this is the first thing to check.

HARBOR_BIN = os.getenv("HARBOR_BIN", shutil.which("harbor") or "")


def _harbor_python() -> Path | None:
    """Harbor's own interpreter.

    Harbor is a uv TOOL install, so it lives in its own venv and the repo's
    .venv cannot import it -- `import harbor` there raises ModuleNotFoundError.
    The driver below therefore runs under Harbor's python, not ours, and this
    script stays runnable from .venv like every other stage.
    """
    if not HARBOR_BIN:
        return None
    py = Path(HARBOR_BIN).resolve().parent / "python"
    return py if py.exists() else None


# Runs under Harbor's interpreter, one argument: the trial directory.
#
# Three things it deliberately does NOT do:
#   * `_init_result()` -- it calls self.agent.to_agent_info(), and self.agent is
#     only set by _prepare() -> _setup_agent(), which is the agent phase we are
#     skipping. It also REWRITES config.json and mints a fresh TrialResult,
#     throwing away the agent record we are trying to preserve. The prior
#     result.json is restored onto _result instead.
#   * `_prepare()` -- builds and starts the agent environment. Nothing in the
#     separate-verifier path touches it (`agent_env_paths` is a paths object,
#     not a live environment), so starting it would cost minutes to build a
#     container that is never used.
#   * `run()` -- its finally block calls _stop_agent_environment() on an
#     environment that was never created.
_PHASE2_DRIVER = r"""
import asyncio, sys
from pathlib import Path
from harbor.models.trial.config import TrialConfig
from harbor.models.trial.result import TrialResult
from harbor.models.task.verifier_mode import (
    VerifierEnvironmentMode, resolve_task_verifier_mode)
from harbor.trial.trial import Trial

trial_dir = Path(sys.argv[1]).resolve()
cfg = TrialConfig.model_validate_json((trial_dir / "config.json").read_text())

# run_task.sh's reshape renames <job>__<id> to trajectory/run_N after the run,
# so the recorded trials_dir/trial_name point at a directory that is now an
# empty stub -- artifacts/_atlas lives only under the new name. Re-point the
# config at where the trial actually is, or the verifier grades an empty tree
# and reports it as an agent that produced nothing.
cfg = cfg.model_copy(update={"trials_dir": trial_dir.parent,
                             "trial_name": trial_dir.name})

async def main() -> int:
    trial = await Trial.create(cfg)
    mode = resolve_task_verifier_mode(trial.task.config)
    if mode != VerifierEnvironmentMode.SEPARATE:
        # Shared mode execs the verifier INTO the agent container, which was
        # torn down when the run ended. It would fail, or worse grade a
        # rebuilt-and-empty world as a real result.
        print("[verifier-rerun] task is environment_mode=%s, not separate; "
              "the verifier runs inside the agent container there and that "
              "container is gone. Migrate the bundle "
              "(scripts/migrate_separate_verifier.py) or re-run the trial."
              % mode.value, file=sys.stderr)
        return 3

    result_path = trial_dir / "result.json"
    if not result_path.exists():
        print("[verifier-rerun] no result.json in %s" % trial_dir, file=sys.stderr)
        return 4
    trial._result = TrialResult.model_validate_json(result_path.read_text())

    # _atlas is either lifted to artifacts/_atlas (post-reshape) or still under
    # the manifest's convention destination (fresh). Reporting only the first
    # spelling prints "present: False" on a run that is about to work fine --
    # a diagnostic that says the opposite of the truth is worse than none.
    found = next((c for c in trial.paths.artifacts_dir.rglob("_atlas")
                  if c.is_dir()), None)
    print("[verifier-rerun] artifacts: %s (_atlas: %s)"
          % (trial.paths.artifacts_dir, found or "NOT FOUND"))
    await trial._run_verifier()
    result_path.write_text(trial.result.model_dump_json(indent=4))
    vr = trial.result.verifier_result
    print("[verifier-rerun] reward=%s" % (getattr(vr, "reward", None),))
    return 0

sys.exit(asyncio.run(main()))
"""


def _dotenv_defaults() -> dict:
    """<repo>/.env as DEFAULTS, mirroring run_task.sh:57-86.

    Same precedence rule as there: the ambient environment wins, .env only
    fills gaps. A subprocess that ignored .env would resolve [verifier.env]
    differently from a normal run, which is the quiet kind of drift that makes
    a re-grade disagree with the original for no visible reason.
    """
    env = {}
    dotenv = REPO / ".env"
    if not dotenv.exists():
        return env
    for line in dotenv.read_text().splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key and key.isidentifier():
            env.setdefault(key, val.strip().strip('"').strip("'"))
    return env


def _missing_verifier_env(task: Path, env: dict) -> list:
    """Names in [verifier.env] that expand to nothing here.

    Harbor resolves these itself and raises ValueError from deep inside
    verifier.verify() -- a 30-line traceback whose one useful line is the
    variable name. It is a credential the operator supplies, not a bug, so it
    is worth catching before anything is built.
    """
    toml_path = task / "task.toml"
    if not toml_path.exists():
        return []
    try:
        import tomllib
        cfg = tomllib.loads(toml_path.read_text())
    except Exception:
        return []
    declared = ((cfg.get("verifier") or {}).get("env") or {})
    missing = []
    for name, value in declared.items():
        ref = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(value).strip())
        if ref and not env.get(ref.group(1)):
            missing.append(ref.group(1))
    return missing


def _atlas_dir(trial: Path) -> Path | None:
    """Where this trial's _atlas lives, in either layout.

    Fresh out of `harbor run` it is under the convention destination the
    manifest records (artifacts/logs/artifacts/_atlas); after run_task.sh's
    reshape it has been lifted to artifacts/_atlas. Both are the same files.
    """
    manifest = _load(trial / "artifacts" / "manifest.json", []) or []
    dest = next((e.get("destination") for e in manifest
                 if e.get("source", "").endswith("/logs/artifacts")), None)
    for candidate in ((trial / dest / "_atlas") if dest else None,
                      trial / "artifacts" / "_atlas"):
        if candidate is not None and candidate.is_dir():
            return candidate
    return None


def _rehydrate_convention_dir(trial: Path) -> int:
    """Undo the reshape's flattening of the artifacts tree, in place.

    Harbor's collect hook records ONE convention entry in manifest.json:

        {"source": "/logs/artifacts", "destination": "artifacts/logs/artifacts"}

    and `upload_artifacts` re-materializes the verifier's /logs/artifacts from
    exactly that destination. But harbor_to_output.py's reshape lifts the real
    payload up a level -- artifacts/logs/artifacts/_atlas becomes
    artifacts/_atlas -- and leaves the recorded destination behind as an EMPTY
    directory.

    That combination is silent and total. `upload_artifacts` finds the path,
    so it does not skip it; it uploads an empty directory; tests/test.sh's
    restore block is guarded by `[ -s ... ]` so it prints nothing and does
    nothing; pytest then grades a run with no trajectory and no world snapshot
    and fails all of it. Measured on run_9: 44 collected, 44 failed, and the
    only hint was the ABSENCE of the "[0/5 restore]" lines.

    So put the payload back where the manifest says it is. Only ever fills an
    empty directory, so it is additive and safe to repeat.
    """
    manifest_path = trial / "artifacts" / "manifest.json"
    manifest = _load(manifest_path, []) or []
    dest = next((e.get("destination") for e in manifest
                 if e.get("source", "").endswith("/logs/artifacts")), None)
    if not dest:
        return 0

    target = trial / dest
    if target.is_dir() and any(target.iterdir()):
        return 0                       # already laid out the way Harbor expects

    # Everything the reshape lifted: the artifacts dir minus Harbor's own
    # bookkeeping and minus the convention path itself.
    src_root = trial / "artifacts"
    top = target.relative_to(src_root).parts[0] if target.is_relative_to(src_root) else None
    payload = [c for c in src_root.iterdir()
               if c.name not in {"manifest.json", "index.json", top}]
    if not payload:
        print(f"[verifier-rerun] {manifest_path.name} points at {dest}, which is "
              f"empty, and there is nothing in artifacts/ to restore it from. "
              f"The verifier would grade an empty run.", file=sys.stderr)
        return 2

    target.mkdir(parents=True, exist_ok=True)
    for child in payload:
        out = target / child.name
        if child.is_dir():
            shutil.copytree(child, out, dirs_exist_ok=True)
        else:
            shutil.copyfile(child, out)
    print(f"[verifier-rerun] rebuilt {dest} from the reshaped tree "
          f"({', '.join(sorted(c.name for c in payload))})")
    return 0


def rerun_verifier(trial: Path, task: Path) -> int:
    """Re-run Phase 2 (pytest + state channel) against an existing trial."""
    py = _harbor_python()
    if py is None:
        print("[verifier-rerun] harbor CLI not found on PATH; set HARBOR_BIN",
              file=sys.stderr)
        return 2
    if not (trial / "config.json").exists():
        print(f"[verifier-rerun] no config.json in {trial}; this is not a trial "
              f"directory Harbor wrote", file=sys.stderr)
        return 2
    # _atlas sits in one of two places depending on whether run_task.sh's reshape
    # has been over this trial yet: under the manifest's convention destination
    # for a fresh trial, and lifted to artifacts/_atlas afterwards. Checking only
    # the reshaped spelling refuses every trial straight out of `harbor run` --
    # which is the common case, not the rare one.
    if not _atlas_dir(trial):
        # Without the collect hook's output there is no world snapshot and no
        # trajectory, so test.sh's restore step finds nothing and pytest grades
        # an empty run -- silently, as an agent that did nothing.
        print(f"[verifier-rerun] no _atlas directory under {trial/'artifacts'}. "
              f"The collect hook never ran for this trial, so the world snapshot "
              f"it needs does not exist and cannot be reconstructed. Re-run the "
              f"trial.", file=sys.stderr)
        return 2

    rc = _rehydrate_convention_dir(trial)
    if rc != 0:
        return rc

    env = {**_dotenv_defaults(), **os.environ}
    missing = _missing_verifier_env(task, env)
    if missing:
        print(f"[verifier-rerun] {task/'task.toml'} declares [verifier.env] "
              f"entries that are empty here: {', '.join(missing)}", file=sys.stderr)
        print(f"[verifier-rerun] these are operator credentials -- export them "
              f"(or add them to {REPO/'.env'}) and re-run", file=sys.stderr)
        return 2

    # tests/test.sh still ATTEMPTS the in-container rubric judge on its way past,
    # and in separate mode that attempt always fails (no codex binary, and the
    # Claude transport needs a credential this phase has no business holding).
    # It then writes a {"per_criterion": []} stub over rubric_breakdown.json --
    # the file Phase 3 publishes from and the file --resume reads its verdicts
    # out of. Re-running pytest must not cost the rubric channel, so the real
    # breakdown is put back afterwards.
    breakdown = trial / "verifier" / "rubric_breakdown.json"
    keep = None
    if (_load(breakdown, {}) or {}).get("per_criterion"):
        keep = breakdown.read_text()
        print(f"[verifier-rerun] holding {breakdown.name} "
              f"({len(json.loads(keep)['per_criterion'])} graded criteria) across "
              f"the verifier run")

    print(f"[verifier-rerun] re-running the verifier phase for {trial.name}")
    # cwd=REPO: config.json records the task as a RELATIVE path
    # (tasks/<task>), so it only resolves from the repo root.
    rc = subprocess.run([str(py), "-c", _PHASE2_DRIVER, str(trial)],
                        cwd=str(REPO), env=env).returncode

    if keep is not None and not (_load(breakdown, {}) or {}).get("per_criterion"):
        breakdown.write_text(keep)
        print(f"[verifier-rerun] restored {breakdown.name}; the in-container "
              f"judge had stubbed it")
    return rc


RUBRIC_JUDGE_IMAGE = os.getenv("RUBRIC_JUDGE_IMAGE", "rubric-judge:latest")


def _image_present(image: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", image],
                          capture_output=True).returncode == 0


def _judge_argv(rubric: Path, traj: Path, out_dir: Path, model, prior: Path | None = None) -> list:
    """argv for one containerised judge call, and only these mounts:

        /in/rubric.json      the rubric being graded               (ro)
        /in/trajectory.json  what the agent did                    (ro)
        /in/prior.json       verdicts to reuse, when resuming      (ro)
        /codex-cred/         one credential file, copied on entry  (ro)
        /out                 scratch dir for the two result files

    Deliberately absent: /workspace, /tests, /logs, the trial tree, the repo.
    The judge cannot read the answer key it is grading against, cannot see the
    other channels' scores, and cannot write anywhere the trial reads except
    through the two files the caller collects afterwards.
    """
    cred = Path.home() / ".codex" / "auth.json"
    argv = [
        "docker", "run", "--rm",
        # Results land owned by the operator rather than root. The image sets
        # HOME=/tmp/judge-home world-writable precisely so an uid it has never
        # heard of still has somewhere for codex to refresh its token.
        "--user", "%d:%d" % (os.getuid(), os.getgid()),
        "-e", "JUDGE_MODEL=%s" % (model or os.getenv("JUDGE_MODEL", "")),
        # Parity pin: compression rewrites the prompt the judge reads, so the
        # container has to inherit the host's setting rather than default.
        "-e", "GRADER_HEADROOM_ENABLED=%s" % os.getenv("GRADER_HEADROOM_ENABLED", "false"),
        "-v", "%s:/in/rubric.json:ro" % rubric.resolve(),
        "-v", "%s:/in/trajectory.json:ro" % traj.resolve(),
        "-v", "%s:/out" % out_dir.resolve(),
    ]
    if cred.exists():
        argv += ["-v", "%s:/codex-cred/auth.json:ro" % cred]
    # The prior breakdown is a file this caller already owns and holds no answer
    # key -- it is the judge's own previous verdicts -- so admitting it read-only
    # keeps the mount contract above intact. It goes in as a SEPARATE file from
    # /out/rubric_breakdown.json so a judge crash, which stubs the output, cannot
    # reach the verdicts being resumed.
    if prior is not None:
        argv += ["-v", "%s:/in/prior.json:ro" % prior.resolve()]
    argv += [RUBRIC_JUDGE_IMAGE,
             "--rubric", "/in/rubric.json",
             "--trajectory", "/in/trajectory.json",
             "--output", "/out/rubric_breakdown.json",
             "--token-output", "/out/judge_tokens.json"]
    if prior is not None:
        argv += ["--resume-from", "/in/prior.json"]
    if model:
        argv += ["--model", model]
    return argv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", required=True, help="output/<job>/<job>__<id>/")
    ap.add_argument("--task", required=True, help="tasks/<task>/")
    ap.add_argument("--model", default=None, help="judge model (default: JUDGE_MODEL, else codex)")
    ap.add_argument("--judge-runner", choices=("container", "host"),
                    default=os.getenv("RUBRIC_JUDGE_RUNNER", "container"),
                    help="where the judge runs (default: container)")
    ap.add_argument("--dry-run", action="store_true", help="convert and report, do not call the judge")
    ap.add_argument("--phase", choices=("rubric", "verifier", "all"), default="rubric",
                    help="which grading phase to re-run. 'rubric' (default) is "
                         "Phase 3 only, the historical behaviour of this script. "
                         "'verifier' re-runs Phase 2 (pytest + state channel) "
                         "against the trial already on disk, without re-running "
                         "the agent -- separate mode only. 'all' does Phase 2 "
                         "then Phase 3, which is the whole grading half of a run")
    ap.add_argument("--resume", action="store_true",
                    help="reuse criteria the trial's existing rubric_breakdown.json "
                         "already graded, under the same judge, transport and "
                         "evidence; only ungraded criteria are re-asked. A partial "
                         "grade (short reply, judge timeout) is what this is for")
    a = ap.parse_args()

    trial, task = Path(a.trial), Path(a.task)
    verifier = trial / "verifier"
    verifier.mkdir(parents=True, exist_ok=True)

    # Phase 2 first when asked, because Phase 3's ledger recompute reads what it
    # writes: reward_channel_a.json and state_channel.json. Running them the
    # other way round would fold a fresh rubric score into the PREVIOUS run's
    # Channel A and publish the mixture as one number.
    if a.phase in ("verifier", "all"):
        rc = rerun_verifier(trial, task)
        if rc != 0:
            print("[host-rubric] verifier phase failed; not grading the rubric "
                  "on top of a half-known result", file=sys.stderr)
            return rc
        if a.phase == "verifier":
            return 0

    rubric = task / "tests" / "rubric.json"
    weights_path = task / "tests" / "test_weights.json"
    if not rubric.exists():
        print(f"[host-rubric] no rubric at {rubric}; nothing to grade", file=sys.stderr)
        return 0

    log = alt.find_agent_log(trial / "agent")
    traj = alt.build_trajectory(log)
    print(f"[host-rubric] agent log: {log}")
    print(f"[host-rubric] {len(traj['steps'])} tool calls, "
          f"final_message {len(traj['final_message'])} chars")
    if not traj["steps"] and not traj["final_message"]:
        print("[host-rubric] empty trajectory; refusing to grade nothing", file=sys.stderr)
        return 1

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(traj, fh)
        traj_path = Path(fh.name)

    breakdown = verifier / "rubric_breakdown.json"
    if a.dry_run:
        print(f"[host-rubric] dry run; trajectory at {traj_path}")
        return 0

    model = a.model or os.getenv("JUDGE_MODEL") or None
    if a.judge_runner == "container" and not _image_present(RUBRIC_JUDGE_IMAGE):
        # No silent fallback to the host. Falling back would grade the run with
        # a different transport than the one the operator asked for and publish
        # the number as if nothing happened -- the exact class of silent drift
        # this split exists to remove.
        print("[host-rubric] judge image %s is not built" % RUBRIC_JUDGE_IMAGE,
              file=sys.stderr)
        print("[host-rubric] run `make build-rubric-judge`, or pass "
              "--judge-runner host to grade on this machine", file=sys.stderr)
        traj_path.unlink(missing_ok=True)
        return 2

    # Resume reads a SNAPSHOT, never the live breakdown. rubric_judge_cli stubs
    # its --output to zeros when the judge crashes, so resuming straight from the
    # file it is about to write would let a failed retry destroy the verdicts it
    # was meant to preserve. The snapshot also stays behind afterwards as the
    # record of what the reused half actually was.
    prior: Path | None = None
    if a.resume:
        if breakdown.exists():
            prior = verifier / "rubric_breakdown.pre_resume.json"
            shutil.copyfile(breakdown, prior)
            print("[host-rubric] [resume] reusing verdicts from %s (%dB)"
                  % (breakdown.name, breakdown.stat().st_size))
        else:
            print("[host-rubric] [resume] no %s in this trial; grading every "
                  "criterion" % breakdown.name)

    print("[host-rubric] judging with %s in the %s ..."
          % (model or "codex default", a.judge_runner))

    if a.judge_runner == "container":
        # The container writes into a scratch dir, never into the trial tree --
        # see _judge_argv. The two results are copied in afterwards.
        out_dir = Path(tempfile.mkdtemp(prefix="rubric-judge-"))
        proc = subprocess.run(_judge_argv(rubric, traj_path, out_dir, model, prior))
        for _name in ("rubric_breakdown.json", "judge_tokens.json"):
            _src = out_dir / _name
            if _src.exists():
                shutil.copyfile(_src, verifier / _name)
        shutil.rmtree(out_dir, ignore_errors=True)
    else:
        cmd = [sys.executable, str(REPO / "services" / "scoring" / "rubric_judge_cli.py"),
               "--rubric", str(rubric), "--trajectory", str(traj_path),
               "--output", str(breakdown),
               "--token-output", str(verifier / "judge_tokens.json")]
        if prior is not None:
            cmd += ["--resume-from", str(prior)]
        if model:
            cmd += ["--model", model]
        proc = subprocess.run(cmd)
    traj_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("[host-rubric] judge failed; rubric channel stays UNSCORED", file=sys.stderr)
        return proc.returncode

    rb = _load(breakdown, {}) or {}
    rubric_value = rb.get("score")
    rubric_value = float(rubric_value) if isinstance(rubric_value, (int, float)) else None

    weights = _load(weights_path, {}) or {}
    _chan_a_path = verifier / "reward_channel_a.json"
    prior = _load(_chan_a_path, {}) or {}
    state = _load(verifier / "state_channel.json", {}) or {}
    chan_a = prior.get("channel_a")
    if chan_a is None:
        print(f"[host-rubric] WARNING: no channel_a in {_chan_a_path.name}; "
              "traj_tests is DROPPED from the ledger and the reward comes from "
              "the rubric alone -- not comparable to a full in-pipeline grade",
              file=sys.stderr)
    rc_val = state.get("completion") if state.get("available") else None
    rb_val = state.get("misbehave") if state.get("available") else None
    guards = prior.get("guards_tripped") or []

    reward, ledger = recompute_reward(weights, chan_a, rubric_value, rc_val, rb_val, guards)

    out = dict(prior)
    out.update({"reward": reward, "rubric": norm_reward(rubric_value),
                "ledger": ledger,
                "rubric_graded_on": "host", "grader": "weighted_ledger"})
    (verifier / "reward_channel_a.json").write_text(json.dumps(out, indent=2))
    (verifier / "reward.json").write_text(json.dumps(
        {"reward": reward,
         "completion_rate": norm_reward(out.get("completion_rate", 0.0)),
         "misbehave_rate": norm_reward(out.get("misbehave_rate", 0.0)),
         "producer": "host_rubric_pass"}, indent=2))

    # Harbor recorded its own reward before this pass ran, so its result.json
    # still holds the rubric-less number. Leaving both on disk means one trial
    # with two different scores and no indication which is current. Update the
    # job-level record to match the ledger.
    _sync_harbor_result(trial, reward)

    print(f"[host-rubric] rubric={rubric_value} channel_a={chan_a} "
          f"state_completion={rc_val} -> reward={fmt_reward(reward)}")
    for name, row in ledger.items():
        print(f"    {name:18} {row.get('status'):9} w={row.get('weight')} "
              f"v={row.get('value', row.get('severity'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
