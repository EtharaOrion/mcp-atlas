"""Unit tests for audit/sandbox.py.

Everything here runs without Docker, harbor or network. A real execute() costs
15-30 minutes, so the parts that can be decided cheaply -- variant resolution,
the swap-and-restore invariant, slug resolution, reward parsing, artifact
hashing -- are decided here, and the real run is left to prove only that the
stages actually fire.

The invariant that matters most is the one in test_swap_restores_*: the sandbox
mutates a task bundle in place, so a crashed run that left a no-op solve.sh
behind would silently poison every later run of that bundle.
"""
import json
import os
import pathlib
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sandbox as sb  # noqa: E402


COMPOSE = """services:
  main:
    build:
      context: .
    command: ["sleep", "infinity"]

  light-servers:
    image: localhost:5000/light-servers@sha256:abc
"""


@pytest.fixture
def task(tmp_path: Path) -> Path:
    """A task bundle with the pieces the sandbox touches."""
    t = tmp_path / "tasks" / "bundle-dir"
    (t / "solution").mkdir(parents=True)
    (t / "environment").mkdir(parents=True)
    (t / "task.toml").write_text('name = "complexmcp/reshaped-slug"\n')
    solve = t / "solution" / "solve.sh"
    solve.write_text("#!/usr/bin/env bash\necho original\n")
    solve.chmod(0o755)
    (t / "environment" / "docker-compose.yaml").write_text(COMPOSE)
    return t


def _plant_run(output_dir: Path, task: Path, out_slug: str, reward: dict,
               rel: str = "trajectory/run_3") -> Path:
    """Fake what the harbor+reshape stages leave on disk."""
    (output_dir / task.name).mkdir(parents=True, exist_ok=True)
    (output_dir / task.name / ".run_state.json").write_text(
        json.dumps({"slug": task.name, "job": task.name, "run_dir": rel})
    )
    run_dir = output_dir / out_slug / rel
    (run_dir / "verifier").mkdir(parents=True)
    (run_dir / "verifier" / "reward.json").write_text(json.dumps(reward))
    (run_dir / "agent").mkdir()
    (run_dir / "agent" / "oracle.txt").write_text("trajectory\n")
    return run_dir


# ---------------------------------------------------------------------------
# variant resolution


def test_oracle_leaves_solve_alone():
    v = sb.Variant.parse("oracle")
    assert (v.agent, v.solve_sh, v.compose_user) == ("oracle", None, None)


def test_empty_is_a_runnable_noop_not_a_blank_file():
    v = sb.Variant.parse("empty")
    assert v.agent == "oracle"
    assert v.solve_sh.strip().endswith("exit 0")
    assert v.solve_sh.startswith("#!")


def test_as_committed_switches_agent_and_keeps_solve():
    v = sb.Variant.parse("as-committed")
    assert (v.agent, v.solve_sh) == ("claude-code", None)


def test_identity_sets_a_non_root_user():
    v = sb.Variant.parse("identity")
    assert v.agent == "oracle"
    assert v.compose_user == "65534:65534"


def test_known_wrong_prefers_the_task_bundle(task, tmp_path, monkeypatch):
    """Controls are per-task -- each encodes one misreading of one document --
    so the bundle's own copy wins over the repo-wide fallback."""
    fallback = tmp_path / "controls"
    fallback.mkdir()
    (fallback / "c7.sh").write_text("#!/usr/bin/env bash\necho fallback\n")
    monkeypatch.setattr(sb, "CONTROLS_DIR", fallback)

    bundle = task / "solution" / "known_wrong"
    bundle.mkdir()
    (bundle / "c7.sh").write_text("#!/usr/bin/env bash\necho bundle\n")

    v = sb.Variant.parse("known-wrong:c7", task)
    assert v.name == "known-wrong:c7"
    assert "bundle" in v.solve_sh


def test_known_wrong_falls_back_to_audit_controls(task, tmp_path, monkeypatch):
    fallback = tmp_path / "controls"
    fallback.mkdir()
    (fallback / "c7.sh").write_text("#!/usr/bin/env bash\necho fallback\n")
    monkeypatch.setattr(sb, "CONTROLS_DIR", fallback)
    assert "fallback" in sb.Variant.parse("known-wrong:c7", task).solve_sh


def test_known_wrong_without_a_control_is_loud(task, tmp_path, monkeypatch):
    """Missing must fail, never no-op: a silently-skipped control is exactly
    how G-RUB-REPLAY passes vacuously."""
    monkeypatch.setattr(sb, "CONTROLS_DIR", tmp_path / "nope")
    with pytest.raises(sb.SandboxError, match="vacuously"):
        sb.Variant.parse("known-wrong:c7", task)


def test_known_wrong_error_lists_where_it_looked(task, tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "CONTROLS_DIR", tmp_path / "nope")
    with pytest.raises(sb.SandboxError, match="known_wrong/c7.sh"):
        sb.Variant.parse("known-wrong:c7", task)


def test_the_nine_shipped_controls_all_resolve():
    """The real bundle's controls, resolved through the real lookup."""
    bundle = (sb.REPO / "tasks" /
              "Amandeep_keelson-district-appropriation-review_48b18e2e-d3b3-4698-8761-73a5454df7ac")
    control_dir = bundle / "solution" / "known_wrong"
    if not control_dir.is_dir():
        pytest.skip("keelson bundle not present")
    ids = sorted(p.stem for p in control_dir.glob("*.sh"))
    assert len(ids) == 9, f"expected nine controls, found {len(ids)}: {ids}"
    for cid in ids:
        v = sb.Variant.parse(f"known-wrong:{cid}", bundle)
        assert v.agent == "oracle"
        assert v.solve_sh.startswith("#!")


def test_the_nine_shipped_controls_mutate_state():
    """A control that only narrates grades identically to `empty`, which is
    precisely the vacuous pass this variant exists to rule out."""
    bundle = (sb.REPO / "tasks" /
              "Amandeep_keelson-district-appropriation-review_48b18e2e-d3b3-4698-8761-73a5454df7ac")
    control_dir = bundle / "solution" / "known_wrong"
    if not control_dir.is_dir():
        pytest.skip("keelson bundle not present")
    for path in sorted(control_dir.glob("*.sh")):
        body = path.read_text()
        assert "call_tool" in body, f"{path.name} performs no MCP calls"


def test_unknown_variant_rejected():
    with pytest.raises(sb.SandboxError, match="unknown variant"):
        sb.Variant.parse("something-else")


# ---------------------------------------------------------------------------
# swap and restore


def test_swap_restores_contents_and_mode(task):
    solve = task / "solution" / "solve.sh"
    before, mode = solve.read_bytes(), solve.stat().st_mode
    with sb._swapped(solve, sb.EMPTY_SOLVE):
        assert solve.read_text() == sb.EMPTY_SOLVE
        assert solve.stat().st_mode & stat.S_IXUSR
    assert solve.read_bytes() == before
    assert solve.stat().st_mode == mode


def test_swap_restores_even_when_the_run_raises(task):
    solve = task / "solution" / "solve.sh"
    before = solve.read_bytes()
    with pytest.raises(ZeroDivisionError):
        with sb._swapped(solve, sb.EMPTY_SOLVE):
            1 / 0
    assert solve.read_bytes() == before


def test_swap_with_none_is_a_noop(task):
    solve = task / "solution" / "solve.sh"
    before = solve.read_bytes()
    with sb._swapped(solve, None):
        assert solve.read_bytes() == before
    assert solve.read_bytes() == before


def test_compose_user_inserted_into_main_only(task):
    out = sb._compose_with_user(COMPOSE, "65534:65534")
    lines = out.splitlines()
    assert lines[lines.index("  main:") + 1] == '    user: "65534:65534"'
    assert out.count("user:") == 1
    # comments and the digest pin survive
    assert "light-servers@sha256:abc" in out


def test_compose_without_main_is_rejected():
    with pytest.raises(sb.SandboxError, match="no `main:` service"):
        sb._compose_with_user("services:\n  other:\n    image: x\n", "1:1")


# ---------------------------------------------------------------------------
# slug resolution


def test_out_slug_comes_from_task_toml_name(task):
    assert sb.resolve_out_slug(task) == "reshaped-slug"


def test_out_slug_falls_back_to_bundle_dir(tmp_path):
    t = tmp_path / "bundle"
    t.mkdir()
    (t / "task.toml").write_text("description = 'no name key'\n")
    assert sb.resolve_out_slug(t) == "bundle"


# ---------------------------------------------------------------------------
# hashing


def test_tree_hash_is_stable_and_content_sensitive(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        (d / "verifier").mkdir(parents=True)
        (d / "verifier" / "reward.json").write_text('{"reward": 1}')
        (d / "x.txt").write_text("same")
    ha, _ = sb._hash_artifacts(a)
    assert sb._hash_artifacts(a)[1] == sb._hash_artifacts(b)[1]
    assert set(ha) == {"verifier/reward.json", "x.txt"}

    (b / "x.txt").write_text("different")
    assert sb._hash_artifacts(a)[1] != sb._hash_artifacts(b)[1]


def test_tree_hash_notices_a_renamed_file(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    (a / "one.txt").write_text("payload")
    (b / "two.txt").write_text("payload")
    assert sb._hash_artifacts(a)[1] != sb._hash_artifacts(b)[1]


# ---------------------------------------------------------------------------
# execute(), with the stages faked out
#
# The fake writes .run_state.json from inside the reshape stage, because that
# is when run_task.sh writes it. Planting it up front instead would make every
# run look like it advanced and would hide the stale-run_dir bug entirely.


def _sandbox(task, tmp_path, monkeypatch, calls, reward=None,
             rel="trajectory/run_3", exits=None):
    s = sb.Sandbox(task, repo=tmp_path, output_dir=tmp_path / "output")
    exits = exits or {}

    def fake_stage(stage, agent):
        calls.append((stage, agent))
        code = exits.get(stage, 0)
        if stage == "reshape" and code == 0 and reward is not None:
            _plant_run(s._active_output, task, s.out_slug, reward, rel)
        return code

    monkeypatch.setattr(s, "_run_stage", fake_stage)
    return s


def test_execute_parses_reward_and_records_stage_order(task, tmp_path, monkeypatch):
    calls = []
    s = _sandbox(task, tmp_path, monkeypatch, calls, reward={
        "reward": 0.75, "completion_rate": 0.9,
        "misbehave_rate": 0.1, "producer": "graded",
    })
    r = s.execute("oracle")

    assert calls == [("harbor", "oracle"), ("reshape", "oracle")]
    assert (r.reward, r.completion_rate, r.misbehave_rate) == (0.75, 0.9, 0.1)
    assert r.producer == "graded"
    assert r.variant == "oracle"
    assert "verifier/reward.json" in r.artifacts
    assert len(r.tree_hash) == 64
    assert json.loads(r.to_json())["reward"] == 0.75


def test_execute_reproduces_the_measured_empty_floor(task, tmp_path, monkeypatch):
    """The numbers the pre-fix oracle actually returned on 2026-09-05."""
    s = _sandbox(task, tmp_path, monkeypatch, [], reward={
        "reward": 0, "completion_rate": 0.092593,
        "misbehave_rate": 0.148148, "producer": "unscored",
    })
    r = s.execute("empty")
    assert r.reward == 0.0
    assert r.completion_rate == pytest.approx(0.092593)
    assert r.producer == "unscored"


def test_execute_routes_as_committed_to_claude_code(task, tmp_path, monkeypatch):
    calls = []
    s = _sandbox(task, tmp_path, monkeypatch, calls, reward={"reward": 0.5})
    r = s.execute("as-committed")
    assert calls == [("harbor", "claude-code"), ("reshape", "claude-code")]
    assert r.agent == "claude-code"


def test_execute_restores_the_bundle_afterwards(task, tmp_path, monkeypatch):
    solve = task / "solution" / "solve.sh"
    compose = task / "environment" / "docker-compose.yaml"
    before = (solve.read_bytes(), compose.read_bytes())

    s = _sandbox(task, tmp_path, monkeypatch, [], reward={"reward": 0})
    s.execute("identity")

    assert (solve.read_bytes(), compose.read_bytes()) == before


def test_execute_restores_the_bundle_even_when_the_run_fails(task, tmp_path, monkeypatch):
    """A failed run must not leave a no-op solve.sh behind: every later run of
    this bundle would then silently be measuring the empty variant."""
    solve = task / "solution" / "solve.sh"
    before = solve.read_bytes()
    s = _sandbox(task, tmp_path, monkeypatch, [], exits={"reshape": 1})
    with pytest.raises(sb.SandboxError):
        s.execute("empty")
    assert solve.read_bytes() == before


def test_execute_sees_the_swap_while_it_runs(task, tmp_path, monkeypatch):
    """Restoring is only correct if the swap was live during the stages."""
    solve = task / "solution" / "solve.sh"
    seen = []
    s = sb.Sandbox(task, repo=tmp_path, output_dir=tmp_path / "output")

    def fake_stage(stage, agent):
        seen.append(solve.read_text())
        if stage == "reshape":
            _plant_run(s._active_output, task, s.out_slug, {"reward": 0})
        return 0

    monkeypatch.setattr(s, "_run_stage", fake_stage)
    s.execute("empty")
    assert seen and all(x == sb.EMPTY_SOLVE for x in seen)
    assert solve.read_text() != sb.EMPTY_SOLVE


# ---------------------------------------------------------------------------
# the advance guard, kept as defence in depth
#
# Per-execution output trees make a stale run_dir unreachable through
# execute(), so the guard is exercised directly. It still matters: it catches a
# reshape that finishes without recording a run of its own.


def test_run_dir_guard_rejects_a_value_that_did_not_advance(task, tmp_path):
    s = sb.Sandbox(task, repo=tmp_path, output_dir=tmp_path / "output")
    s._active_output = tmp_path / "output"
    _plant_run(s._active_output, task, s.out_slug, {"reward": 1}, "trajectory/run_7")
    with pytest.raises(sb.SandboxError, match="did not advance"):
        s._run_dir("trajectory/run_7", {"harbor": 0, "reshape": 1})


def test_run_dir_guard_reports_stage_exits(task, tmp_path):
    s = sb.Sandbox(task, repo=tmp_path, output_dir=tmp_path / "output")
    s._active_output = tmp_path / "output"
    _plant_run(s._active_output, task, s.out_slug, {"reward": 1}, "trajectory/run_7")
    with pytest.raises(sb.SandboxError, match=r"'reshape': 1"):
        s._run_dir("trajectory/run_7", {"harbor": 0, "reshape": 1})


def test_run_dir_guard_accepts_an_advanced_value(task, tmp_path):
    s = sb.Sandbox(task, repo=tmp_path, output_dir=tmp_path / "output")
    s._active_output = tmp_path / "output"
    _plant_run(s._active_output, task, s.out_slug, {"reward": 1}, "trajectory/run_8")
    assert s._run_dir("trajectory/run_7", {"harbor": 0, "reshape": 0}).name == "run_8"


# ---------------------------------------------------------------------------
# error paths


def test_missing_reward_json_is_an_error_not_a_zero(task, tmp_path, monkeypatch):
    """A run that produced nothing must not be reported as reward 0.0 --
    that is the difference between a floor and a broken harness."""
    s = sb.Sandbox(task, repo=tmp_path, output_dir=tmp_path / "output")

    def fake_stage(stage, agent):
        if stage == "reshape":
            run_dir = s._active_output / s.out_slug / "trajectory/run_3"
            run_dir.mkdir(parents=True)
            (s._active_output / task.name).mkdir(parents=True, exist_ok=True)
            (s._active_output / task.name / ".run_state.json").write_text(
                json.dumps({"run_dir": "trajectory/run_3"}))
        return 0

    monkeypatch.setattr(s, "_run_stage", fake_stage)
    with pytest.raises(sb.SandboxError, match="no reward.json"):
        s.execute("oracle")


def test_missing_run_state_is_an_error(task, tmp_path, monkeypatch):
    s = _sandbox(task, tmp_path, monkeypatch, [])
    with pytest.raises(sb.SandboxError, match="no run state"):
        s.execute("oracle")


def test_run_state_without_run_dir_is_an_error(task, tmp_path, monkeypatch):
    s = sb.Sandbox(task, repo=tmp_path, output_dir=tmp_path / "output")

    def fake_stage(stage, agent):
        (s._active_output / task.name).mkdir(parents=True, exist_ok=True)
        (s._active_output / task.name / ".run_state.json").write_text("{}")
        return 0

    monkeypatch.setattr(s, "_run_stage", fake_stage)
    with pytest.raises(sb.SandboxError, match="no run_dir"):
        s.execute("oracle")


def test_non_task_dir_rejected(tmp_path):
    with pytest.raises(sb.SandboxError, match="not a task dir"):
        sb.Sandbox(tmp_path)


# ---------------------------------------------------------------------------
# reward range


@pytest.mark.parametrize("value,flagged", [(0.0, False), (1.0, False),
                                           (0.185185, False), (10.47, True),
                                           (-0.5, True)])
def test_reward_out_of_range_flag(task, tmp_path, monkeypatch, value, flagged):
    """host_rubric_pass emitted reward 10.47 on the first real run through this
    surface. Report it; do not clamp it into looking valid."""
    s = _sandbox(task, tmp_path, monkeypatch, [], reward={"reward": value})
    r = s.execute("oracle")
    assert r.reward_out_of_range is flagged
    assert json.loads(r.to_json())["reward_out_of_range"] is flagged


# ---------------------------------------------------------------------------
# per-execution output isolation
#
# Found by running the nine controls on 2026-09-05: sharing one output tree
# across variants let harbor_to_output.py's re-reshape shuffle run_N, and two
# different controls came back with byte-identical rewards.


def test_each_variant_gets_its_own_output_tree(task, tmp_path, monkeypatch):
    seen = []
    s = sb.Sandbox(task, repo=tmp_path, output_dir=tmp_path / "output")

    def fake_stage(stage, agent):
        seen.append(s._active_output)
        if stage == "reshape":
            _plant_run(s._active_output, task, s.out_slug, {"reward": 0.5}, "trajectory/run_1")
        return 0

    monkeypatch.setattr(s, "_run_stage", fake_stage)
    a = s.execute("oracle")
    b = s.execute("empty")

    assert a.run_dir != b.run_dir
    assert "oracle" in str(a.run_dir) and "empty" in str(b.run_dir)
    assert len(set(seen)) == 2, "both variants shared one output tree"


def test_rerunning_a_variant_starts_from_a_clean_tree(task, tmp_path, monkeypatch):
    """A stale run_1 left by a previous execution of the SAME variant must not
    be readable as this execution's result."""
    s = sb.Sandbox(task, repo=tmp_path, output_dir=tmp_path / "output")
    calls = {"n": 0}

    def fake_stage(stage, agent):
        if stage == "reshape":
            calls["n"] += 1
            _plant_run(s._active_output, task, s.out_slug,
                       {"reward": 0.1 * calls["n"]}, "trajectory/run_1")
        return 0

    monkeypatch.setattr(s, "_run_stage", fake_stage)
    first = s.execute("empty")
    second = s.execute("empty")
    assert first.reward != second.reward
    assert second.reward == pytest.approx(0.2)


def test_stale_tree_from_a_prior_variant_is_not_reused(task, tmp_path, monkeypatch):
    """If reshape fails, the fresh tree has no run_dir at all -- so the run
    errors instead of silently inheriting another variant's numbers."""
    s = sb.Sandbox(task, repo=tmp_path, output_dir=tmp_path / "output")

    def ok_stage(stage, agent):
        if stage == "reshape":
            _plant_run(s._active_output, task, s.out_slug, {"reward": 0.9}, "trajectory/run_1")
        return 0

    monkeypatch.setattr(s, "_run_stage", ok_stage)
    s.execute("oracle")

    monkeypatch.setattr(s, "_run_stage", lambda stage, agent: 1)
    with pytest.raises(sb.SandboxError, match="no run state|no run_dir"):
        s.execute("empty")


# ---------------------------------------------------------------------------
# delivery conformance
#
# Measured on three identical oracle runs: 3 distinct tree hashes, 23 shared
# files, only 6 byte-stable. So conformance is set membership plus a hash check
# restricted to the reproducible subset -- never whole-tree equality.


def _exec(artifacts, variant="oracle"):
    return sb.Execution(variant=variant, agent="oracle", run_dir=pathlib.Path("/x"),
                        reward=0.5, completion_rate=0.6, misbehave_rate=0.1,
                        producer="host_rubric_pass", artifacts=artifacts, tree_hash="h")


BASE = {
    "artifacts/index.json": "a", "artifacts/manifest.json": "b",
    "logs/light-servers-health.log": "c", "verifier/end_env.json": "d",
    "verifier/grade_report.md": "e", "verifier/state_channel.json": "f",
    "verifier/rubric_breakdown.json": "volatile-1", "agent/oracle.txt": "volatile-1",
}


def test_conformance_passes_when_stable_files_match_and_sets_agree():
    a = _exec(dict(BASE))
    b = _exec({**BASE, "verifier/rubric_breakdown.json": "volatile-2",
               "agent/oracle.txt": "volatile-2"})
    r = sb.conformance([a, b])
    assert r["conformant"] is True
    assert r["set_conformant"] is True
    assert r["stable_violations"] == []
    assert len(r["stable_checked"]) == 6


def test_conformance_flags_a_changed_artifact_set():
    """The tuple edit moved a real run from 23 files to 24; that must show."""
    a = _exec(dict(BASE))
    b = _exec({**BASE, "verifier/reward_channel_a.json": "new"})
    r = sb.conformance([a, b])
    assert r["conformant"] is False
    assert r["set_diffs"][0]["extra"] == ["verifier/reward_channel_a.json"]


def test_conformance_flags_an_unstable_supposedly_stable_file():
    a = _exec(dict(BASE))
    b = _exec({**BASE, "verifier/end_env.json": "CHANGED"})
    r = sb.conformance([a, b])
    assert r["conformant"] is False
    assert r["stable_violations"] == ["verifier/end_env.json"]


def test_conformance_ignores_volatile_files_entirely():
    """Whole-tree hashing fails here; that must not be what conformance means."""
    a = _exec(dict(BASE))
    b = _exec({**BASE, "verifier/rubric_breakdown.json": "totally-different"})
    assert sb.conformance([a, b])["conformant"] is True


def test_conformance_reports_stable_files_absent_from_the_run():
    thin = {"artifacts/index.json": "a"}
    r = sb.conformance([_exec(thin), _exec(dict(thin))])
    assert "verifier/end_env.json" in r["stable_absent"]
    assert r["stable_checked"] == ["artifacts/index.json"]


def test_conformance_needs_two_runs():
    with pytest.raises(sb.SandboxError, match="at least two runs"):
        sb.conformance([_exec(dict(BASE))])


def test_rubric_judge_failed_is_not_treated_as_stable():
    """test.sh now writes the judge's real error there, so it varies."""
    assert "verifier/rubric_judge_failed.txt" not in sb.STABLE_ARTIFACTS


# ---------------------------------------------------------------------------
# reward integrity: the reported reward must match the ledger it summarises
#
# The range check alone caught the 2026-09-05 x100 defect only because 100x
# happened to leave [0, 1]. These cases are the ones it cannot see.

LEDGER = {"traj_tests": {"weight": 10.7, "value": 0.5556},
          "rubric": {"weight": 3.79, "value": 0.3465}}


def _rw(reward, ledger=LEDGER):
    return sb.Execution(variant="v", agent="oracle", run_dir=pathlib.Path("/x"),
                        reward=reward, completion_rate=0.6, misbehave_rate=0.1,
                        producer="host_rubric_pass", ledger=ledger)


def test_ledger_reward_is_the_weighted_mean_of_scored_components():
    assert _rw(0.0).ledger_reward == pytest.approx(0.500908, abs=1e-6)


def test_consistent_when_reward_matches_the_ledger():
    assert _rw(0.500875).reward_consistent is True


def test_the_x100_defect_is_caught():
    e = _rw(50.09)
    assert e.reward_consistent is False
    assert e.reward_out_of_range is True


def test_a_halved_reward_is_caught_though_it_stays_in_range():
    """The case a range check cannot see."""
    e = _rw(0.25)
    assert e.reward_out_of_range is False
    assert e.reward_consistent is False


def test_an_arbitrary_wrong_reward_in_range_is_caught():
    e = _rw(0.9)
    assert e.reward_out_of_range is False
    assert e.reward_consistent is False


def test_null_valued_components_leave_the_denominator():
    """An unscored channel must not drag the score toward zero -- it is
    excluded, matching recompute_reward in scripts/host_rubric_pass.py."""
    led = {"traj_tests": {"weight": 10.7, "value": None},
           "rubric": {"weight": 3.79, "value": 0.3465}}
    assert _rw(0.3465, led).ledger_reward == pytest.approx(0.3465)
    assert _rw(0.3465, led).reward_consistent is True


def test_missing_ledger_reports_none_not_a_pass():
    """No ledger is a gap in the evidence, not a clean bill of health."""
    assert _rw(0.5, {}).reward_consistent is None
    assert _rw(0.5, {}).ledger_reward is None


def test_consistency_is_serialised():
    d = json.loads(_rw(0.500875).to_json())
    assert d["reward_consistent"] is True
    assert d["ledger_reward"] == pytest.approx(0.500908, abs=1e-6)
