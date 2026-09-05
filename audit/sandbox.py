"""Concrete sandbox surface for the Group A gaps.

CALIBRATION, DELIVERY-CONFORMANCE, REWARD-INTEGRITY and RUBRIC-COMPILATION all
stall in the same place: the execution precondition holds -- the attestation
cleared the authorisation -- but nothing implements `Sandbox.execute()`. This
is that implementation. It wraps the pipeline that was proved by hand on
2026-09-05 and nothing more:

    swap solution/solve.sh for the variant
    AGENT=<agent> scripts/run_task.sh --stage harbor
    AGENT=<agent> scripts/run_task.sh --stage reshape
    parse   output/<slug>/trajectory/run_N/verifier/reward.json
    hash    every artifact under that run dir

The five variants differ only in what gets swapped in and which agent runs, so
they share one swap mechanism (`_swapped`) rather than five code paths:

    oracle           the working-tree solve.sh, run by harbor's oracle agent
    empty            a no-op solve.sh -- the floor. Reproduces the 0-byte
                     /logs/agent/oracle.txt that scored reward 0.0 /
                     completion_rate 0.092593 before solve.sh grew its
                     executable half.
    known-wrong:<id> a control from audit/controls/<id>.sh
    as-committed     solve.sh untouched; AGENT=claude-code actually attempts it
    identity         oracle, but the compose `main` service gains a `user:` so
                     the run executes under a non-root uid

Runtime, not code, is the cost here: 15-30 minutes per execute(), so a full
sweep is an overnight job. Everything in this module that can be checked
without spending that is checked in audit/tests/test_sandbox.py against fakes.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

REPO = Path(__file__).resolve().parent.parent
CONTROLS_DIR = Path(__file__).resolve().parent / "controls"

# A solve.sh that runs, exits clean, and writes nothing. Not an empty file:
# harbor executes this path and a zero-byte script is indistinguishable from a
# missing one in the logs. The floor has to be a deliberate no-op.
EMPTY_SOLVE = """#!/usr/bin/env bash
# variant: empty -- deliberate no-op floor. Runs, exits 0, mutates nothing.
set -euo pipefail
exit 0
"""

_STAGES = ("harbor", "reshape")


# Artifacts that are byte-identical across repeat runs of the same variant, so
# they can be hash-compared for delivery conformance. Measured across three
# identical oracle runs on 2026-09-05: only these held. The other sixteen files
# in a run vary every time -- rubric_breakdown.json carries nondeterministic
# judge output, and even agent/oracle.txt differs because the light-servers
# session_id is embedded in every recorded call. A whole-tree hash therefore
# reports three distinct values for three identical runs and is useless as a
# conformance signal; set membership plus this subset is the check that works.
#
# rubric_judge_failed.txt was byte-stable too, but only because its content was
# a fixed five-word string. tests/test.sh now writes the judge's real error
# there, so it varies and is deliberately NOT listed.
STABLE_ARTIFACTS = frozenset({
    "artifacts/index.json",
    "artifacts/manifest.json",
    "logs/light-servers-health.log",
    "verifier/end_env.json",
    "verifier/grade_report.md",
    "verifier/state_channel.json",
    # Stable for a reason that will not last: the in-container rubric judge
    # fails identically on every run ("codex CLI not found on PATH"), so both
    # files carry the same bytes each time. When RUBRIC-COMPILATION is fixed
    # they will change or disappear, and this check SHOULD fail then -- that is
    # a delivered-set change and conformance exists to notice it. Re-measure
    # and update deliberately at that point rather than pre-emptively.
    "verifier/rubric_judge_failed.txt",
    "verifier/rubric_judge.log",
})

# Delivered and auditable, but NOT hash-checkable: reward_channel_a.json embeds
# the run's rubric and reward values, which move with the judge. Set membership
# covers its presence; its content is checked by reward_consistent instead.


class SandboxError(RuntimeError):
    """Raised when a variant cannot be resolved or a run produced no reward."""


@dataclass(frozen=True)
class Variant:
    """A resolved variant: what to run and what to swap in before running it."""

    name: str
    agent: str
    solve_sh: str | None = None      # None = leave the task's solve.sh alone
    compose_user: str | None = None  # None = leave the task's compose alone

    @classmethod
    def parse(cls, spec: str, task: Path | None = None) -> "Variant":
        if spec == "oracle":
            # The working-tree solve.sh IS the oracle variant; swapping it for
            # a copy of itself would be a no-op, so leave it in place.
            return cls("oracle", agent="oracle")
        if spec == "empty":
            return cls("empty", agent="oracle", solve_sh=EMPTY_SOLVE)
        if spec == "as-committed":
            return cls("as-committed", agent="claude-code")
        if spec == "identity":
            # Non-root uid. 65534:65534 is nobody:nogroup on the slim images
            # this bundle builds on.
            return cls("identity", agent="oracle", compose_user="65534:65534")
        if spec.startswith("known-wrong:"):
            control_id = spec.split(":", 1)[1]
            if not control_id:
                raise SandboxError("known-wrong: needs a control id")
            for path in cls._control_paths(control_id, task):
                if path.is_file():
                    return cls(f"known-wrong:{control_id}", agent="oracle",
                               solve_sh=path.read_text())
            looked = ", ".join(str(p) for p in cls._control_paths(control_id, task))
            raise SandboxError(
                f"no control {control_id!r} (looked in: {looked}). Controls must "
                "exist AND mutate state -- one that only narrates a wrong answer "
                "grades identically to the empty variant, and G-RUB-REPLAY then "
                "passes vacuously."
            )
        raise SandboxError(f"unknown variant: {spec!r}")


    @staticmethod
    def _control_paths(control_id: str, task: Path | None) -> list[Path]:
        """Where a known-wrong control may live, most specific first.

        The controls are per-task by nature -- each encodes one misreading of
        one document -- so the bundle's own solution/known_wrong/ wins over the
        repo-wide audit/controls/ fallback.
        """
        paths = []
        if task is not None:
            paths.append(task / "solution" / "known_wrong" / f"{control_id}.sh")
        paths.append(CONTROLS_DIR / f"{control_id}.sh")
        return paths


@dataclass(frozen=True)
class Execution:
    """What one execute() produced. Everything the four gaps need to compare."""

    variant: str
    agent: str
    run_dir: Path
    reward: float
    completion_rate: float
    misbehave_rate: float
    producer: str
    artifacts: dict[str, str] = field(default_factory=dict)
    tree_hash: str = ""
    stages: dict[str, int] = field(default_factory=dict)
    ledger: dict = field(default_factory=dict)

    @property
    def ledger_reward(self) -> float | None:
        """The reward the run's own ledger implies: sum(w*v)/sum(w).

        Components with a null value are excluded rather than counted as zero,
        matching recompute_reward in scripts/host_rubric_pass.py -- an unscored
        channel leaves the denominator, it does not drag the score down.
        """
        scored = {k: v for k, v in (self.ledger or {}).items()
                  if isinstance(v, dict) and v.get("value") is not None}
        den = sum(float(v.get("weight") or 0) for v in scored.values())
        if not den:
            return None
        return sum(float(v["weight"]) * float(v["value"]) for v in scored.values()) / den

    @property
    def reward_consistent(self) -> bool | None:
        """Does the reported reward match the ledger it summarises?

        This is the reward-integrity property, and it is strictly stronger than
        the range check below. The 2026-09-05 defect reported 50.09 against a
        ledger implying 0.5009 -- caught here as a factor-of-100 mismatch, and
        caught by the range check only because 100x happened to leave [0, 1].
        A x0.5 bug, or a reward of 0.9 against a ledger saying 0.4, is invisible
        to a range check and visible here. None when there is no ledger to
        check against, which is itself worth surfacing rather than passing.
        """
        implied = self.ledger_reward
        if implied is None:
            return None
        return abs(self.reward - implied) <= 1e-4

    @property
    def reward_out_of_range(self) -> bool:
        """Reward outside [0, 1].

        Not hypothetical: the host_rubric_pass fallback producer emits a raw
        rubric score, so the first real run through this surface returned
        reward 10.47 while completion_rate stayed 0.185. Callers comparing a
        variant against the oracle must not read that as a 10x result, so the
        anomaly is reported rather than clamped -- clamping would hide it.
        """
        return not (0.0 <= self.reward <= 1.0)

    def to_json(self) -> str:
        doc = {
            "variant": self.variant,
            "agent": self.agent,
            "run_dir": str(self.run_dir),
            "reward": self.reward,
            "completion_rate": self.completion_rate,
            "misbehave_rate": self.misbehave_rate,
            "producer": self.producer,
            "reward_out_of_range": self.reward_out_of_range,
            "ledger_reward": self.ledger_reward,
            "reward_consistent": self.reward_consistent,
            "tree_hash": self.tree_hash,
            "stages": self.stages,
            "artifacts": self.artifacts,
        }
        return json.dumps(doc, indent=2, sort_keys=True)


def resolve_out_slug(task: Path) -> str:
    """Where the reshaper writes, which is NOT always the bundle dir name.

    harbor_to_output.py names the reshaped tree from task.toml's `name` (last
    path segment) and falls back to the bundle dir. run_task.sh does the same
    thing in shell; this has to agree with it or we read the wrong run dir.
    """
    toml = task / "task.toml"
    if toml.is_file():
        m = re.search(r'^\s*name\s*=\s*"([^"]+)"', toml.read_text(), re.MULTILINE)
        if m:
            name = m.group(1).rsplit("/", 1)[-1]
            if name:
                return name
    return task.name


@contextlib.contextmanager
def _swapped(path: Path, new_text: str | None) -> Iterator[None]:
    """Temporarily replace `path`'s contents, restoring the original bytes.

    Restores in a finally, so a crashed or killed-mid-run harbor still leaves
    the task bundle exactly as it was found. `None` means don't touch it.
    """
    if new_text is None:
        yield
        return
    original = path.read_bytes()
    mode = path.stat().st_mode
    try:
        path.write_text(new_text)
        os.chmod(path, mode)
        yield
    finally:
        path.write_bytes(original)
        os.chmod(path, mode)


def _compose_with_user(compose_text: str, user: str) -> str:
    """Insert `user:` into the compose `main` service.

    Textual, not a yaml round-trip: this file's comments carry the digest-pin
    reasoning and a yaml.dump would silently drop all of them.
    """
    lines = compose_text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if re.match(r"^  main:\s*$", line):
            lines.insert(i + 1, f'    user: "{user}"\n')
            return "".join(lines)
    raise SandboxError("compose has no `main:` service to set user on")


def _hash_artifacts(run_dir: Path) -> tuple[dict[str, str], str]:
    """sha256 every file under run_dir, plus one hash over the whole tree.

    Sorted relative paths, so the tree hash is stable across filesystems and
    two runs that produced identical bytes hash identically.
    """
    digests: dict[str, str] = {}
    for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        digests[str(path.relative_to(run_dir))] = h.hexdigest()

    tree = hashlib.sha256()
    for rel, digest in digests.items():
        tree.update(rel.encode())
        tree.update(b"\0")
        tree.update(digest.encode())
        tree.update(b"\n")
    return digests, tree.hexdigest()


class Sandbox:
    """Runs one task bundle under a named variant and reports what came back."""

    def __init__(
        self,
        task: Path | str,
        *,
        repo: Path = REPO,
        output_dir: Path | None = None,
        timeout: int = 3600,
        env: dict[str, str] | None = None,
    ) -> None:
        self.repo = Path(repo).resolve()
        self.task = Path(task).resolve()
        if not (self.task / "task.toml").is_file():
            raise SandboxError(f"not a task dir (no task.toml): {self.task}")
        self.output_dir = Path(output_dir).resolve() if output_dir else self.repo / "output"
        self.timeout = timeout
        self.env = env or {}
        self.out_slug = resolve_out_slug(self.task)
        self._active_output = self.output_dir

    # -- stage driving ------------------------------------------------------

    @staticmethod
    def _slug(variant_name: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in variant_name)

    def _run_stage(self, stage: str, agent: str) -> int:
        """One `scripts/run_task.sh --stage <stage>` invocation.

        Two calls rather than STAGE=harbor,reshape: run_task.sh's dispatch
        takes a single stage, and teaching a shared script comma syntax for
        one caller is the wrong place to put it.
        """
        env = {**os.environ, **self.env, "AGENT": agent,
               "OUTPUT_DIR": str(self._active_output)}
        proc = subprocess.run(
            [str(self.repo / "scripts" / "run_task.sh"), "--stage", stage, str(self.task)],
            cwd=self.repo, env=env, timeout=self.timeout,
        )
        return proc.returncode

    @property
    def _state_file(self) -> Path:
        """run_task.sh keys this by the bundle dir name, not the output slug."""
        return self._active_output / self.task.name / ".run_state.json"

    def _recorded_run_dir(self) -> str | None:
        """`run_dir` as it currently stands, or None. Relative to the out slug."""
        if not self._state_file.is_file():
            return None
        try:
            return json.loads(self._state_file.read_text()).get("run_dir")
        except (json.JSONDecodeError, OSError):
            return None

    def _run_dir(self, prior: str | None, stages: dict[str, int]) -> Path:
        """The run THIS execute() owns -- never a previous one's.

        stage_reshape writes run_dir as its last act, so a reshape that dies
        earlier leaves the previous execute()'s value in place. Reading it
        without checking is how two different variants come back with byte-
        identical rewards: the second one never ran, it re-read the first.
        Measured on 2026-09-05 -- `empty` reported the oracle's run_7 and its
        reward of 10.47 because host_rubric_pass exited 1 before run_dir was
        updated. So the value must have ADVANCED, not merely be present.
        """
        if not self._state_file.is_file():
            raise SandboxError(
                f"no run state at {self._state_file}; harbor stage never ran "
                f"(stage exits: {stages})"
            )
        rel = self._recorded_run_dir()
        if not rel:
            raise SandboxError(
                f"{self._state_file} has no run_dir; reshape never finished "
                f"(stage exits: {stages})"
            )
        if rel == prior:
            raise SandboxError(
                f"run_dir did not advance past {rel!r}: this execute() produced "
                f"no run of its own, so the numbers on disk belong to a previous "
                f"variant. Stage exits: {stages}."
            )
        run_dir = self._active_output / self.out_slug / rel
        if not run_dir.is_dir():
            raise SandboxError(f"state points at a missing run dir: {run_dir}")
        return run_dir

    # -- the surface --------------------------------------------------------

    def execute(self, variant: str | Variant) -> Execution:
        """Run one variant end to end and return its parsed, hashed result."""
        v = Variant.parse(variant, self.task) if isinstance(variant, str) else variant

        solve = self.task / "solution" / "solve.sh"
        compose = self.task / "environment" / "docker-compose.yaml"
        compose_text = (
            _compose_with_user(compose.read_text(), v.compose_user)
            if v.compose_user else None
        )

        # Every execution gets its OWN output tree. Sharing one tree across
        # variants is not merely untidy: harbor_to_output.py re-reshapes the
        # whole accumulating job dir on every invocation (deliberately, for
        # pass@k), so trajectory/run_N is not a stable per-execution identity.
        # Measured 2026-09-05 running the nine controls: three correct, fully
        # distinct trajectories were emitted, then duplicated across six run
        # dirs, and .run_state.json pointed the third control at the second
        # control's trial -- two different controls reported the same reward
        # and nothing looked wrong. The advance-check below cannot catch that
        # on its own, because the value does advance; it just advances to
        # somebody else's run.
        self._active_output = self.output_dir / "_sandbox" / self._slug(v.name)
        if self._active_output.exists():
            shutil.rmtree(self._active_output)
        self._active_output.mkdir(parents=True)

        # Snapshot before the run so a stage that dies without updating it is
        # detectable afterwards.
        prior = self._recorded_run_dir()

        stages: dict[str, int] = {}
        with _swapped(solve, v.solve_sh), _swapped(compose, compose_text):
            for stage in _STAGES:
                stages[stage] = self._run_stage(stage, v.agent)

        run_dir = self._run_dir(prior, stages)
        reward_path = run_dir / "verifier" / "reward.json"
        if not reward_path.is_file():
            raise SandboxError(
                f"run produced no reward.json at {reward_path} "
                f"(stage exits: {stages})"
            )
        reward = json.loads(reward_path.read_text())
        artifacts, tree_hash = _hash_artifacts(run_dir)

        detail = run_dir / "verifier" / "detail.json"
        ledger: dict = {}
        if detail.is_file():
            try:
                ledger = json.loads(detail.read_text()).get("ledger") or {}
            except (json.JSONDecodeError, OSError):
                ledger = {}

        return Execution(
            variant=v.name,
            agent=v.agent,
            run_dir=run_dir,
            reward=float(reward.get("reward", 0.0)),
            completion_rate=float(reward.get("completion_rate", 0.0)),
            misbehave_rate=float(reward.get("misbehave_rate", 0.0)),
            producer=str(reward.get("producer", "")),
            artifacts=artifacts,
            tree_hash=tree_hash,
            stages=stages,
            ledger=ledger,
        )


def conformance(runs: Sequence["Execution"],
                stable: frozenset[str] = STABLE_ARTIFACTS) -> dict:
    """Compare repeat runs of one variant for delivery conformance.

    Two questions, kept separate because they fail for different reasons:
    does every run ship the same SET of artifacts, and do the files that are
    supposed to be reproducible actually hash the same? Whole-tree equality is
    not asked, because it is never true (see STABLE_ARTIFACTS).
    """
    if len(runs) < 2:
        raise SandboxError("conformance needs at least two runs to compare")

    sets = [frozenset(r.artifacts) for r in runs]
    baseline = sets[0]
    set_diffs = [
        {"run": i, "missing": sorted(baseline - s), "extra": sorted(s - baseline)}
        for i, s in enumerate(sets) if s != baseline
    ]

    checked = sorted(stable & baseline)
    unstable = []
    for name in checked:
        digests = {r.artifacts.get(name) for r in runs}
        if len(digests) > 1:
            unstable.append(name)

    absent = sorted(stable - baseline)
    return {
        "runs": len(runs),
        "set_conformant": not set_diffs,
        "set_diffs": set_diffs,
        "stable_checked": checked,
        "stable_absent": absent,
        "stable_violations": unstable,
        "conformant": not set_diffs and not unstable,
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Execute one task bundle under a sandbox variant.")
    ap.add_argument("task", type=Path)
    ap.add_argument("--variant", default="oracle")
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args(argv)

    sandbox = Sandbox(args.task, output_dir=args.output_dir, timeout=args.timeout)
    print(sandbox.execute(args.variant).to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
