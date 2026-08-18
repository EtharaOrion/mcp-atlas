"""Unit tests for services/scoring/weighted_judge.py."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import weighted_judge as wj  # noqa: E402

TRAJECTORY = {
    "schema_version": "mcp-atlas-trajectory-v1",
    "session_id": "s1",
    "task_id": "t1",
    "agent": {"name": "litellm", "model_name": "test-model"},
    "final_metrics": {
        "total_prompt_tokens": 10,
        "total_completion_tokens": 10,
        "total_cost_usd": None,
        "total_steps": 2,
    },
    "steps": [
        {
            "step_id": 1,
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "arxiv_search_papers", "arguments": "{}"},
                    }
                ],
            },
            "tool_results": [
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "content": [{"type": "text", "text": "found 3 papers"}],
                }
            ],
        },
    ],
}

TEST_OUTPUTS_PY = '''
from traj_asserts import called_with, called_any

def test_used_arxiv_search():
    assert called_with("arxiv_search_papers")

def test_called_distractor_slack_tool():
    # guard: passing here means the forbidden thing happened
    assert called_any("slack_channels_list")

def test_never_true():
    assert False
'''


def _write_test_file(tmp_path):
    p = tmp_path / "test_outputs.py"
    p.write_text(TEST_OUTPUTS_PY, encoding="utf-8")
    return p


def test_run_traj_pytest_reports_pass_fail(tmp_path):
    test_file = _write_test_file(tmp_path)
    results = wj._run_traj_pytest(TRAJECTORY, test_file)
    assert results == {
        "test_used_arxiv_search": True,
        "test_called_distractor_slack_tool": False,
        "test_never_true": False,
    }


def test_run_traj_pytest_missing_file_returns_empty(tmp_path):
    assert wj._run_traj_pytest(TRAJECTORY, tmp_path / "nope.py") == {}


def test_load_weights_missing_file_is_inert(tmp_path):
    weights = wj.load_weights(tmp_path / "nope.json")
    assert weights.traj_tests.weight == 0.0
    assert weights.traj_tests.tests == {}


def test_load_weights_flat_shape_stays_inert(tmp_path):
    p = tmp_path / "test_weights.json"
    p.write_text(json.dumps({"test_used_arxiv_search": 1, "test_called_distractor_slack_tool": -2}))
    weights = wj.load_weights(p)
    assert weights.traj_tests.weight == 0.0  # flat shape never opts a task in
    assert weights.traj_tests.tests == {
        "test_used_arxiv_search": 1,
        "test_called_distractor_slack_tool": -2,
    }


def test_load_weights_component_shape(tmp_path):
    p = tmp_path / "test_weights.json"
    p.write_text(json.dumps({
        "threshold": 0.8,
        "components": {
            "traj_tests": {
                "weight": 3,
                "tests": {"test_used_arxiv_search": 1, "test_called_distractor_slack_tool": -2},
            },
            "rubric": {"weight": 5},
        },
    }))
    weights = wj.load_weights(p)
    assert weights.threshold == 0.8
    assert weights.traj_tests.weight == 3.0
    assert weights.rubric.weight == 5.0


def test_score_traj_tests_goal_and_guard():
    weights = {"test_used_arxiv_search": 1, "test_called_distractor_slack_tool": -2}
    # goal passed, guard did NOT trigger -> full credit
    assert wj.score_traj_tests(
        {"test_used_arxiv_search": True, "test_called_distractor_slack_tool": False}, weights
    ) == 1.0
    # goal passed, guard DID trigger -> penalized down to floor 0
    assert wj.score_traj_tests(
        {"test_used_arxiv_search": True, "test_called_distractor_slack_tool": True}, weights
    ) == 0.0
    # goal failed -> no credit regardless of guard
    assert wj.score_traj_tests(
        {"test_used_arxiv_search": False, "test_called_distractor_slack_tool": False}, weights
    ) == 0.0


def test_score_traj_tests_no_goals_returns_none():
    weights = {"test_called_distractor_slack_tool": -2}
    assert wj.score_traj_tests({"test_called_distractor_slack_tool": False}, weights) is None


def test_traj_test_rows_outcomes():
    weights = {"test_used_arxiv_search": 1, "test_called_distractor_slack_tool": -2, "test_not_collected": 1}
    results = {"test_used_arxiv_search": True, "test_called_distractor_slack_tool": True}
    rows = {r["name"]: r["outcome"] for r in wj.traj_test_rows(results, weights)}
    assert rows == {
        "test_used_arxiv_search": "credited",
        "test_called_distractor_slack_tool": "penalized",
        "test_not_collected": "not_run",
    }


def test_score_task_end_to_end(tmp_path):
    test_file = _write_test_file(tmp_path)
    weights_file = tmp_path / "test_weights.json"
    weights_file.write_text(json.dumps({
        "components": {
            "traj_tests": {
                "weight": 3,
                "tests": {"test_used_arxiv_search": 1, "test_called_distractor_slack_tool": -2},
            }
        }
    }))
    result = wj.score_task(TRAJECTORY, test_file, weights_file)
    assert result["weight"] == 3.0
    assert result["value"] == 1.0  # goal passed, guard didn't trigger
    assert len(result["rows"]) == 2


def test_run_twice_does_not_leak_state(tmp_path):
    """Two back-to-back runs against different trajectories in the same
    process must not leak traj_asserts cache or module state."""
    test_file = _write_test_file(tmp_path)
    other_trajectory = {**TRAJECTORY, "steps": []}
    first = wj._run_traj_pytest(TRAJECTORY, test_file)
    second = wj._run_traj_pytest(other_trajectory, test_file)
    assert first["test_used_arxiv_search"] is True
    assert second["test_used_arxiv_search"] is False
