"""Template for a task's tests/test_outputs.py — Channel A (trajectory
assertions), graded by services/scoring/weighted_judge.py.

Copy this into a task's tests/ dir alongside a test_weights.json (see
test_weights.example.json in this same directory) and edit both to fit the
task.

FORBIDDEN here: reading the agent's final free-text message for factual
content — that's Channel B's job (tests/rubric.json / GTFA_CLAIMS), graded
separately by services/scoring/score_claims.py. This file may only inspect
*which tools were called, with what arguments* — never whether the content
of the final answer is factually correct.

Every assert below is phrased positively ("X happened"). Whether that's good
news or bad news is decided by the *sign* of this test's weight in
test_weights.json — never by writing `assert not ...` here:

  * a "goal" test (positive weight) should assert the thing you *want* to
    have happened.
  * a "guard" test (negative weight) should assert the *forbidden* thing
    happened — i.e. it's written to describe the violation, and it PASSES
    when the violation occurred. The penalty then comes from the negative
    weight, not from inverting the assertion.

See services/scoring/traj_asserts.py for the full assertion API
(calls, called_with, called_any, never_called, call_count,
distinct_tools_called, tool_errored, final).
"""
from traj_asserts import called_with, called_any


def test_touched_target_tool():
    """Goal (positive weight): the agent used a tool this task actually
    needs. Replace with the real tool name(s) for this task."""
    assert called_any("REPLACE_WITH_TARGET_TOOL_NAME")


def test_called_distractor_tool():
    """Guard (negative weight): calling one of these tools means the agent
    went down an unrelated distractor path. Passing means the forbidden
    thing happened — the penalty comes from this test's negative weight in
    test_weights.json, not from the assertion's phrasing."""
    assert called_any("REPLACE_WITH_DISTRACTOR_TOOL_NAME")


def test_called_target_tool_with_expected_argument():
    """Goal (positive weight): example of checking a specific argument, not
    just that the tool was called at all."""
    assert called_with("REPLACE_WITH_TARGET_TOOL_NAME", REPLACE_ARG_NAME="REPLACE_EXPECTED_VALUE")
