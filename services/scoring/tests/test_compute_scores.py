"""Unit tests for rubric_judge_cli._compute_scores.

This function turns the judge's per-criterion verdicts into the rubric score,
and it had no coverage at all. A rename of `weight` to `score` collapsed two
lines into one and took `num = str(c.get("number", ""))` with it, so every call
raised NameError. The bundle catches that and writes

    {"rubric_passed": false, "per_criterion": [], "error": "name 'num' is not defined"}

which reads as "the rubric was graded and the run earned nothing" rather than
"the grader crashed". host_rubric_pass then refused to grade, and a 91-step run
was published at reward 0.0 with no indication that anything had broken.

The first test below is the one that matters: it fails with NameError on the
unfixed function.

The second half of the file covers `--resume-from`, which lives in the same
module and turns on the same rows: reuse is only sound if `_compute_scores`
records enough about each verdict -- which judge produced it, over which
evidence, and whether the judge answered at all -- for a later pass to decide
whether it may be reused.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rubric_judge_cli as rj  # noqa: E402


def _criteria():
    return [
        {"number": 1, "criterion": "restated total is correct", "score": 2,
         "is_positive": True},
        {"number": 2, "criterion": "fabricated a figure", "score": 3,
         "is_positive": False},
    ]


def test_verdicts_are_matched_to_criteria_by_number():
    """The join is by criterion number, not by list position.

    The judge may return verdicts in any order, and may return fewer than it
    was asked for. Matching positionally would silently attribute one
    criterion's verdict to another -- and dropping the `num` lookup entirely is
    what broke the function.
    """
    out = rj._compute_scores(
        _criteria(),
        # deliberately reversed relative to the criteria order
        [{"number": 2, "satisfied": False, "justification": "no fabrication"},
         {"number": 1, "satisfied": True, "justification": "total checks out"}],
    )
    by_num = {p["number"]: p for p in out["per_criterion"]}
    assert by_num["1"]["satisfied"] is True
    assert by_num["1"]["justification"] == "total checks out"
    assert by_num["2"]["satisfied"] is False


def test_every_criterion_is_reported_even_with_no_verdict():
    """A criterion the judge never returned is still a row, scored unsatisfied.

    Silently dropping it would shrink the denominator and inflate the score of
    a run the judge only partially graded.
    """
    out = rj._compute_scores(_criteria(), [{"number": 1, "satisfied": True}])
    assert len(out["per_criterion"]) == 2
    assert {p["number"] for p in out["per_criterion"]} == {"1", "2"}


def test_positive_criteria_earn_and_negative_criteria_penalise():
    """rc is credit earned on positives; rb is severity hit on negatives."""
    all_good = rj._compute_scores(
        _criteria(),
        [{"number": 1, "satisfied": True}, {"number": 2, "satisfied": False}],
    )
    all_bad = rj._compute_scores(
        _criteria(),
        [{"number": 1, "satisfied": False}, {"number": 2, "satisfied": True}],
    )
    assert all_good["rc"] > all_bad["rc"]
    assert all_bad["rb"] > all_good["rb"]


def test_criterion_weight_is_carried_through_under_its_published_name():
    """The per-criterion weight is published as `score`.

    The rename that broke `num` also renamed this field; the report and the
    breakdown both read it, so it is part of the contract.
    """
    out = rj._compute_scores(_criteria(), [{"number": 1, "satisfied": True}])
    by_num = {p["number"]: p for p in out["per_criterion"]}
    assert by_num["1"]["score"] == 2.0
    assert by_num["2"]["score"] == 3.0


# ---------------------------------------------------------------------------
# Resume: reuse criteria a previous judge pass already graded.
#
# One `codex exec` call grades the WHOLE rubric, so a reply that comes back short
# -- truncated, unparseable, or killed by the 600s timeout -- used to cost the
# entire pass. A missing number reads as satisfied=False above, which is
# indistinguishable on disk from a criterion the judge answered "no" to, and the
# only way back was to re-ask all of them and pay the ~14.5K-token scaffold plus
# up to 300K chars of evidence again.
#
# The tests that matter here are the refusal ones. Reuse is only sound when the
# prior verdicts were measured under the conditions this run measures under; a
# merged score is wrong in a way no later reader can detect, so a mismatch has to
# regrade rather than quietly blend two populations.

MODEL = "gpt-5.6-sol"


def _graded_prior(criteria, identity, *, ungraded=()):
    """A prior breakdown, shaped as rubric_judge_cli would have written it."""
    return {
        "score": 1.0, "rc": 1.0, "rb": 0.0, "rubric_passed": True,
        "meta": {"identity": identity, "criteria_total": len(criteria)},
        "per_criterion": [
            {"number": str(c["number"]), "criterion": c["criterion"],
             "score": c["score"], "is_positive": c["is_positive"],
             "satisfied": True, "justification": "prior verdict",
             "graded": str(c["number"]) not in {str(n) for n in ungraded},
             "fingerprint": rj._criterion_fingerprint(c), "reused": False}
            for c in criteria
        ],
    }


def _write(tmp_path, doc, name="prior.json"):
    path = tmp_path / name
    path.write_text(json.dumps(doc))
    return path


def test_a_different_judge_model_refuses_the_reuse(tmp_path):
    """gpt-5.6-sol and claude-sonnet-4-5 are not one population.

    The breakdown declares ONE model. Merging verdicts from two of them
    publishes a single score, under a single declared judge, drawn from both --
    and nothing downstream can tell.
    """
    criteria = _criteria()
    prior = _write(tmp_path, _graded_prior(
        criteria, rj._resume_identity("claude-sonnet-4-5", "steps", "final")))

    reused, meta = rj._load_resume(
        prior, rj._resume_identity(MODEL, "steps", "final"), criteria)

    assert reused == []
    assert meta["decision"] == "refused"
    assert "judge_model" in meta["divergent_fields"]
    assert "judge_transport" in meta["divergent_fields"]
    assert meta["criteria_regraded"] == 2


def test_a_rebuilt_trajectory_refuses_the_reuse(tmp_path):
    """Prior verdicts answer a question about the evidence they were shown.

    Re-running after the trajectory was rebuilt -- a longer agent log, a changed
    evidence budget, a fixed builder -- means those verdicts are about a
    different artifact, however unchanged the rubric is.
    """
    criteria = _criteria()
    prior = _write(tmp_path, _graded_prior(
        criteria, rj._resume_identity(MODEL, "the agent did one thing", "final")))

    reused, meta = rj._load_resume(
        prior,
        rj._resume_identity(MODEL, "the agent did one thing, then another", "final"),
        criteria,
    )

    assert reused == []
    assert meta["divergent_fields"] == ["evidence_sha256"]


def test_headroom_compression_refuses_the_reuse(tmp_path, monkeypatch):
    """GRADER_HEADROOM_ENABLED rewrites the prompt the judge reads.

    host_rubric_pass pins it into the judge container precisely so the two sides
    agree, so a compressed-evidence verdict and an uncompressed one are not
    interchangeable either.
    """
    criteria = _criteria()
    monkeypatch.setenv("GRADER_HEADROOM_ENABLED", "false")
    prior = _write(tmp_path, _graded_prior(
        criteria, rj._resume_identity(MODEL, "steps", "final")))

    monkeypatch.setenv("GRADER_HEADROOM_ENABLED", "true")
    reused, meta = rj._load_resume(
        prior, rj._resume_identity(MODEL, "steps", "final"), criteria)

    assert reused == []
    assert meta["divergent_fields"] == ["headroom"]


def test_matching_identity_reuses_every_graded_criterion(tmp_path):
    criteria = _criteria()
    identity = rj._resume_identity(MODEL, "steps", "final")
    prior = _write(tmp_path, _graded_prior(criteria, identity))

    reused, meta = rj._load_resume(prior, identity, criteria)

    assert meta["decision"] == "accepted"
    assert meta["criteria_reused"] == 2
    assert meta["criteria_regraded"] == 0
    assert [r["number"] for r in reused] == ["1", "2"]
    assert all(r["reused"] is True for r in reused)


def test_an_ungraded_criterion_is_re_asked_not_reused(tmp_path):
    """`graded: false` is a hole in the measurement, not a verdict.

    This is the whole point of the flag: the judge never answered for this
    criterion, _compute_scores wrote it out as satisfied=False like any other
    unmet one, and only the `graded` field separates the two.
    """
    criteria = _criteria()
    identity = rj._resume_identity(MODEL, "steps", "final")
    prior = _write(tmp_path, _graded_prior(criteria, identity, ungraded=[2]))

    reused, meta = rj._load_resume(prior, identity, criteria)

    assert [r["number"] for r in reused] == ["1"]
    assert meta["criteria_reused"] == 1
    assert meta["criteria_regraded"] == 1


def test_an_edited_criterion_is_re_asked_under_the_same_number(tmp_path):
    """Number alone is not identity -- the same slot can hold a new question."""
    identity = rj._resume_identity(MODEL, "steps", "final")
    prior = _write(tmp_path, _graded_prior(_criteria(), identity))

    edited = _criteria()
    edited[1]["criterion"] = "fabricated a figure OR a citation"
    reused, meta = rj._load_resume(prior, identity, edited)

    assert [r["number"] for r in reused] == ["1"]
    assert meta["criteria_regraded"] == 1


def test_two_criteria_sharing_a_number_do_not_share_one_verdict(tmp_path):
    """Keying on number alone would copy one verdict onto both."""
    criteria = [
        {"number": 1, "criterion": "first question", "score": 1, "is_positive": True},
        {"number": 1, "criterion": "second question", "score": 1, "is_positive": True},
    ]
    identity = rj._resume_identity(MODEL, "steps", "final")
    doc = _graded_prior(criteria, identity)
    doc["per_criterion"] = doc["per_criterion"][:1]     # only the first was graded
    prior = _write(tmp_path, doc)

    reused, meta = rj._load_resume(prior, identity, criteria)

    assert len(reused) == 1
    assert meta["criteria_regraded"] == 1


def test_a_prior_row_without_a_fingerprint_is_regraded(tmp_path):
    """Breakdowns written before this field cannot be matched, only trusted."""
    criteria = _criteria()
    identity = rj._resume_identity(MODEL, "steps", "final")
    doc = _graded_prior(criteria, identity)
    for row in doc["per_criterion"]:
        row.pop("fingerprint")
    prior = _write(tmp_path, doc)

    reused, meta = rj._load_resume(prior, identity, criteria)

    assert reused == []
    assert meta["decision"] == "accepted"      # identity matched; the rows did not
    assert meta["criteria_regraded"] == 2


def test_reuse_is_counted_over_this_run_s_criteria_not_the_prior_file(tmp_path):
    """A rubric that GAINED a criterion must not report reuse that never happened."""
    identity = rj._resume_identity(MODEL, "steps", "final")
    prior = _write(tmp_path, _graded_prior(_criteria(), identity))

    grown = _criteria() + [
        {"number": 3, "criterion": "cited its source", "score": 1, "is_positive": True}]
    reused, meta = rj._load_resume(prior, identity, grown)

    assert meta["criteria_reused"] == 2
    assert meta["criteria_regraded"] == 1
    assert len(reused) + meta["criteria_regraded"] == len(grown)


def test_compute_scores_records_whether_the_judge_actually_answered():
    """Without `graded`, an unanswered criterion is a reusable-looking false."""
    out = rj._compute_scores(
        _criteria(), [{"number": 1, "satisfied": True, "justification": "ok"}])
    by_num = {p["number"]: p for p in out["per_criterion"]}

    assert by_num["1"]["graded"] is True
    assert by_num["2"]["graded"] is False
    assert by_num["2"]["satisfied"] is False          # scoring itself is unchanged
    assert by_num["1"]["fingerprint"] == rj._criterion_fingerprint(_criteria()[0])


def test_reused_verdicts_are_marked_in_the_breakdown():
    out = rj._compute_scores(
        _criteria(),
        [{"number": "1", "satisfied": True, "justification": "prior", "reused": True},
         {"number": "2", "satisfied": False, "justification": "fresh"}])
    by_num = {p["number"]: p for p in out["per_criterion"]}

    assert by_num["1"]["reused"] is True
    assert by_num["2"]["reused"] is False


def test_a_reused_verdict_scores_exactly_as_a_fresh_one():
    """Reuse changes who paid for the verdict, never what it is worth."""
    fresh = rj._compute_scores(
        _criteria(),
        [{"number": "1", "satisfied": True}, {"number": "2", "satisfied": False}])
    resumed = rj._compute_scores(
        _criteria(),
        [{"number": "1", "satisfied": True, "reused": True},
         {"number": "2", "satisfied": False, "reused": True}])

    assert (fresh["score"], fresh["rc"], fresh["rb"]) == \
           (resumed["score"], resumed["rc"], resumed["rb"])


# --- end to end through main() ----------------------------------------------


def _run_main(tmp_path, monkeypatch, criteria, *, resume_from=None, judge=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    rubric = tmp_path / "rubric.json"
    rubric.write_text(json.dumps(criteria))
    traj = tmp_path / "traj.json"
    traj.write_text(json.dumps(
        {"steps": [{"tool": "bash", "input": "ls"}], "final_message": "done"}))
    out = tmp_path / "out" / "rubric_breakdown.json"

    monkeypatch.setattr(rj, "_preflight", lambda model: None)
    if judge is not None:
        monkeypatch.setattr(rj, "_run_judge", judge)

    argv = ["rubric_judge_cli.py", "--rubric", str(rubric), "--trajectory", str(traj),
            "--output", str(out), "--model", MODEL]
    if resume_from is not None:
        argv += ["--resume-from", str(resume_from)]
    monkeypatch.setattr(sys, "argv", argv)
    rj.main()
    return json.loads(out.read_text())


def _identity_for_the_fixture_trajectory():
    traj = {"steps": [{"tool": "bash", "input": "ls"}], "final_message": "done"}
    return rj._resume_identity(MODEL, rj._render_trajectory(traj), "done")


def test_a_fully_reusable_rubric_never_calls_the_judge(tmp_path, monkeypatch):
    """The saving, stated plainly: zero judge calls, same score."""
    criteria = _criteria()

    async def _explode(*args, **kwargs):
        raise AssertionError("the judge must not be called when nothing is pending")

    async def _judge(crit, traj_ctx, final_ctx, model):
        return [{"number": str(c["number"]), "satisfied": True, "justification": "y"}
                for c in crit]

    # Grade once for real, so the prior breakdown carries this run's identity.
    first = _run_main(tmp_path / "a", monkeypatch, criteria, judge=_judge)
    prior = _write(tmp_path, first, "prior.json")

    second = _run_main(tmp_path / "b", monkeypatch, criteria,
                       resume_from=prior, judge=_explode)

    assert second["meta"]["resume"]["decision"] == "accepted"
    assert second["meta"]["resume"]["criteria_reused"] == 2
    assert second["score"] == first["score"]
    assert all(p["reused"] is True for p in second["per_criterion"])


def test_only_the_ungraded_criteria_reach_the_judge(tmp_path, monkeypatch):
    criteria = _criteria()
    prior = _write(tmp_path, _graded_prior(
        criteria, _identity_for_the_fixture_trajectory(), ungraded=[2]))

    asked = []

    async def _judge(crit, traj_ctx, final_ctx, model):
        asked.extend(str(c["number"]) for c in crit)
        return [{"number": str(c["number"]), "satisfied": False, "justification": "n"}
                for c in crit]

    doc = _run_main(tmp_path / "b", monkeypatch, criteria,
                    resume_from=prior, judge=_judge)

    assert asked == ["2"], "the judge was re-asked a criterion it had already graded"
    by_num = {p["number"]: p for p in doc["per_criterion"]}
    assert by_num["1"]["reused"] is True and by_num["1"]["satisfied"] is True
    assert by_num["2"]["reused"] is False


def test_an_empty_judge_reply_still_fails_loudly_under_resume(tmp_path, monkeypatch):
    """The reused half must not carry an empty reply past the UNSCORED guard.

    Checking the merged list instead of the pending subset would publish the
    re-asked criteria as a block of silent falses -- exactly what that guard
    exists to prevent -- and would do it while looking like a partial success.
    """
    criteria = _criteria()
    prior = _write(tmp_path, _graded_prior(
        criteria, _identity_for_the_fixture_trajectory(), ungraded=[2]))

    async def _judge(crit, traj_ctx, final_ctx, model):
        return []

    with pytest.raises(SystemExit) as exc:
        _run_main(tmp_path / "b", monkeypatch, criteria,
                  resume_from=prior, judge=_judge)

    assert exc.value.code == 1
    assert not (tmp_path / "b" / "out" / "rubric_breakdown.json").exists(), \
        "a failed resume must leave the prior verdicts as the only file on disk"


def test_resuming_from_the_output_file_is_refused(tmp_path, monkeypatch):
    """A judge crash stubs --output to zeros; that must not be the resume source."""
    rubric = tmp_path / "rubric.json"
    rubric.write_text(json.dumps(_criteria()))
    traj = tmp_path / "traj.json"
    traj.write_text(json.dumps({"steps": [], "final_message": "done"}))
    out = tmp_path / "rubric_breakdown.json"
    out.write_text(json.dumps({"per_criterion": []}))

    monkeypatch.setattr(sys, "argv", [
        "rubric_judge_cli.py", "--rubric", str(rubric), "--trajectory", str(traj),
        "--output", str(out), "--resume-from", str(out), "--model", MODEL])

    with pytest.raises(SystemExit) as exc:
        rj.main()
    assert exc.value.code == 2


def test_a_missing_resume_file_grades_everything(tmp_path, monkeypatch):
    """Falling back to a full pass beats refusing to grade."""
    async def _judge(crit, traj_ctx, final_ctx, model):
        assert len(crit) == 2
        return [{"number": str(c["number"]), "satisfied": True} for c in crit]

    doc = _run_main(tmp_path / "b", monkeypatch, _criteria(),
                    resume_from=tmp_path / "nope.json", judge=_judge)

    assert "resume" not in doc["meta"]
    assert doc["meta"]["identity"]["judge_model"] == MODEL
