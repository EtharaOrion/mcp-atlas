"""Validates WEIGHTED_JUDGE_ENTRY_TEMPLATE's actual runtime behavior -- the
string convert_tasks_to_harbor.py / adapters/mcp_atlas/adapter.py write
verbatim into tests/weighted_judge_entry.py inside a --weighted Harbor
bundle. This is Phase 7's "no behavior change by default" proof: an inert
test_weights.json (both components weight 0, exactly what TEST_WEIGHTS_JSON_STUB
ships) must leave a pre-existing reward.json -- the one agent_judge.py would
have already written -- completely untouched.

The template is a plain string constant (not an importable module, since
it's meant to be `uv run` standalone inside a container), so this test execs
it into a throwaway module inside a tmp "/tests"-equivalent directory that
also holds real copies of traj_asserts.py and weighted_judge.py, then calls
its parameterized main(agent_dir=..., out_dir=..., tests_dir=...).
"""
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from convert_tasks_to_harbor import (  # noqa: E402
    TEST_WEIGHTS_JSON_STUB,
    WEIGHTED_JUDGE_ENTRY_TEMPLATE,
    _read_scoring_module_source,
)


def _load_entry_module(tests_dir: Path) -> types.ModuleType:
    """Recreates the exact /tests layout a --weighted bundle ships, then
    execs weighted_judge_entry.py's source as a module with tests_dir on
    sys.path (mirroring how `uv run /tests/weighted_judge_entry.py` sees
    /tests inside the real container)."""
    (tests_dir / "traj_asserts.py").write_text(_read_scoring_module_source("traj_asserts.py"), encoding="utf-8")
    (tests_dir / "weighted_judge.py").write_text(_read_scoring_module_source("weighted_judge.py"), encoding="utf-8")
    entry_path = tests_dir / "weighted_judge_entry.py"
    # Strip the PEP 723 `# /// script ... # ///` header -- it's a comment,
    # harmless either way, but not needed for an in-process exec.
    entry_path.write_text(WEIGHTED_JUDGE_ENTRY_TEMPLATE, encoding="utf-8")

    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    module = types.ModuleType("weighted_judge_entry")
    module.__file__ = str(entry_path)
    exec(compile(entry_path.read_text(encoding="utf-8"), str(entry_path), "exec"), module.__dict__)
    return module


def _write_trajectory(agent_dir: Path, tool_name: str = "search") -> None:
    agent_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"type": "message", "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": tool_name, "arguments": "{}"}}],
        }}),
        json.dumps({"type": "result", "result": "done"}),
    ]
    (agent_dir / "trajectory.txt").write_text("\n".join(lines), encoding="utf-8")


def test_inert_weights_leaves_existing_reward_json_untouched(tmp_path):
    """The core Phase 5/6 safety guarantee: a --weighted bundle whose
    test_weights.json was never edited (TEST_WEIGHTS_JSON_STUB's inert
    default) must not alter the reward.json agent_judge.py already wrote."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    agent_dir = tmp_path / "logs" / "agent"
    out_dir = tmp_path / "logs" / "verifier"
    out_dir.mkdir(parents=True)

    (tests_dir / "test_weights.json").write_text(TEST_WEIGHTS_JSON_STUB, encoding="utf-8")
    (tests_dir / "test_outputs.py").write_text("# no tests opted in\n", encoding="utf-8")
    _write_trajectory(agent_dir)

    # Simulate agent_judge.py having already run and scored this task.
    (out_dir / "reward.json").write_text(json.dumps({"reward": 0.8}), encoding="utf-8")
    (out_dir / "reward.txt").write_text("0.8", encoding="utf-8")

    module = _load_entry_module(tests_dir)
    module.main(agent_dir=agent_dir, out_dir=out_dir, tests_dir=tests_dir)

    assert json.loads((out_dir / "reward.json").read_text()) == {"reward": 0.8}
    assert (out_dir / "reward.txt").read_text() == "0.8"
    # Still emits detail.json for visibility even when inert.
    detail = json.loads((out_dir / "detail.json").read_text())
    assert detail["reward"] is None


def test_opted_in_traj_tests_overwrites_reward_json(tmp_path):
    """Once a task author actually opts a component in, the combined reward
    DOES overwrite reward.json -- confirming the inert case above isn't
    just "main() never writes anything"."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    agent_dir = tmp_path / "logs" / "agent"
    out_dir = tmp_path / "logs" / "verifier"
    out_dir.mkdir(parents=True)

    (tests_dir / "test_weights.json").write_text(json.dumps({
        "components": {"traj_tests": {"weight": 1, "tests": {"test_used_search": 1}}, "rubric": {"weight": 0}}
    }), encoding="utf-8")
    (tests_dir / "test_outputs.py").write_text(
        'from traj_asserts import called_with\n'
        'def test_used_search():\n'
        '    assert called_with("search")\n',
        encoding="utf-8",
    )
    _write_trajectory(agent_dir, tool_name="search")

    (out_dir / "reward.json").write_text(json.dumps({"reward": 0.0}), encoding="utf-8")

    module = _load_entry_module(tests_dir)
    module.main(agent_dir=agent_dir, out_dir=out_dir, tests_dir=tests_dir)

    result = json.loads((out_dir / "reward.json").read_text())
    assert result == {"reward": 1.0}


def test_opted_in_rubric_reuses_agent_judge_breakdown(tmp_path):
    """rubric.weight > 0 reads agent_judge.py's own rubric_breakdown.json
    (score + results) rather than re-judging -- confirming Channel B in a
    Harbor bundle is a pure combine, not a duplicate LLM call."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    agent_dir = tmp_path / "logs" / "agent"
    out_dir = tmp_path / "logs" / "verifier"
    out_dir.mkdir(parents=True)

    (tests_dir / "test_weights.json").write_text(json.dumps({
        "components": {"traj_tests": {"weight": 0, "tests": {}}, "rubric": {"weight": 1}}
    }), encoding="utf-8")
    (tests_dir / "test_outputs.py").write_text("# unused, traj_tests weight 0\n", encoding="utf-8")
    _write_trajectory(agent_dir)

    (out_dir / "reward.json").write_text(json.dumps({"reward": 0.5}), encoding="utf-8")
    (out_dir / "rubric_breakdown.json").write_text(json.dumps({
        "score": 0.5, "results": [{"id": "claim_000", "result": True}],
    }), encoding="utf-8")

    module = _load_entry_module(tests_dir)
    module.main(agent_dir=agent_dir, out_dir=out_dir, tests_dir=tests_dir)

    result = json.loads((out_dir / "reward.json").read_text())
    assert result == {"reward": 0.5}
    detail = json.loads((out_dir / "detail.json").read_text())
    assert detail["ledger"]["rubric"] == {"weight": 1.0, "value": 0.5}


def _write_claude_code_trajectory(agent_dir: Path) -> None:
    """The stream-json dialect Harbor's claude-code agent writes to
    /logs/agent/claude-code.txt: tool calls are `tool_use` content blocks on
    `type: assistant` events, results are `tool_result` blocks on `type: user`
    events, and MCP tools are namespaced `mcp__<server>__<tool>`."""
    agent_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"type": "system", "subtype": "init", "tools": ["mcp__mcp-atlas__search"]}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Looking it up."},
            {"type": "tool_use", "id": "toolu_1", "name": "mcp__mcp-atlas__search",
             "input": {"query": "xenon"}},
        ]}}),
        json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1",
             "content": [{"type": "text", "text": "Xenon, 54"}]},
        ]}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {"command": "echo hi"}},
        ]}}),
        json.dumps({"type": "result", "subtype": "success", "result": "54"}),
    ]
    (agent_dir / "claude-code.txt").write_text("\n".join(lines), encoding="utf-8")


def test_parses_claude_code_stream_json_and_strips_mcp_prefix(tmp_path):
    """Regression: with Harbor's claude-code agent, Channel A used to see zero
    tool calls (wrong event shape + `mcp__<server>__` prefix) and every task
    scored 0 on traj_tests regardless of what the agent did."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    agent_dir = tmp_path / "logs" / "agent"
    out_dir = tmp_path / "logs" / "verifier"
    out_dir.mkdir(parents=True)

    (tests_dir / "test_weights.json").write_text(json.dumps({
        "components": {"traj_tests": {"weight": 1, "tests": {
            "test_used_search": 1, "test_search_args": 1, "test_saw_bash": 1}},
            "rubric": {"weight": 0}}
    }), encoding="utf-8")
    (tests_dir / "test_outputs.py").write_text(
        'from traj_asserts import called_any, calls\n'
        'def test_used_search():\n'
        '    assert called_any("search")\n'
        'def test_search_args():\n'
        '    assert any(c.name == "search" and c.arguments.get("query") == "xenon" for c in calls())\n'
        'def test_saw_bash():\n'
        '    assert called_any("Bash")\n',
        encoding="utf-8",
    )
    _write_claude_code_trajectory(agent_dir)

    module = _load_entry_module(tests_dir)

    messages, response = module.load_flat_messages_and_response(str(agent_dir / "claude-code.txt"))
    assert response == "54"
    names = [tc["function"]["name"] for m in messages for tc in (m.get("tool_calls") or [])]
    assert names == ["search", "Bash"]
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "toolu_1" for m in messages)

    module.main(agent_dir=agent_dir, out_dir=out_dir, tests_dir=tests_dir)
    assert json.loads((out_dir / "reward.json").read_text()) == {"reward": 1.0}


def test_openai_dialect_also_strips_mcp_prefix(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    agent_dir = tmp_path / "logs" / "agent"
    _write_trajectory(agent_dir, tool_name="mcp__mcp-atlas__search")
    module = _load_entry_module(tests_dir)
    messages, _ = module.load_flat_messages_and_response(str(agent_dir / "trajectory.txt"))
    assert messages[0]["tool_calls"][0]["function"]["name"] == "search"


def _rubric_bundle(tests_dir: Path, out_dir: Path, breakdown: dict) -> None:
    """A rubric-only bundle: traj_tests inert, Channel B carrying all the weight."""
    (tests_dir / "rubric_weighted.py").write_text(
        _read_scoring_module_source("rubric_weighted.py"), encoding="utf-8"
    )
    (tests_dir / "test_weights.json").write_text(json.dumps({
        "components": {"traj_tests": {"weight": 0, "tests": {}}, "rubric": {"weight": 1}}
    }), encoding="utf-8")
    (tests_dir / "test_outputs.py").write_text("# unused\n", encoding="utf-8")
    (tests_dir / "rubric.json").write_text(json.dumps({"criteria": [
        {"number": 1, "criterion": "did the good thing", "weight": 2, "is_positive": True},
        {"number": 2, "criterion": "did the other good thing", "weight": 2, "is_positive": True},
        {"number": 3, "criterion": "fell into the trap", "weight": 1, "is_positive": False},
    ]}), encoding="utf-8")
    (out_dir / "reward.json").write_text(json.dumps({"reward": 0.0}), encoding="utf-8")
    (out_dir / "rubric_breakdown.json").write_text(json.dumps(breakdown), encoding="utf-8")


def _run_rubric(tmp_path: Path, breakdown: dict) -> float:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    agent_dir = tmp_path / "logs" / "agent"
    out_dir = tmp_path / "logs" / "verifier"
    out_dir.mkdir(parents=True)
    _rubric_bundle(tests_dir, out_dir, breakdown)
    _write_trajectory(agent_dir)
    module = _load_entry_module(tests_dir)
    module.main(agent_dir=agent_dir, out_dir=out_dir, tests_dir=tests_dir)
    return json.loads((out_dir / "reward.json").read_text())["reward"]


# One judge pass, written under either writer's schema, must score the same.
# rubric_judge_cli emits per_criterion/number/satisfied; the harbor entry
# template emits results/id/score. Reading only the latter sent every
# rubric_judge_cli run to the all-or-nothing fallback, so criterion 1 below --
# genuinely satisfied, and already paid for in judge tokens -- scored zero.
_TEMPLATE_SCHEMA = {"score": 0.5, "results": [
    {"id": "1", "score": 1.0}, {"id": "2", "score": 0.0}, {"id": "3", "score": 0.0},
]}
_JUDGE_CLI_SCHEMA = {"rubric_passed": False, "per_criterion": [
    {"number": 1, "satisfied": True}, {"number": 2, "satisfied": False},
    {"number": 3, "satisfied": False},
]}


def test_rubric_breakdown_schemas_agree(tmp_path):
    """Both writers' schemas reach the weighted branch and land on one value."""
    template = _run_rubric(tmp_path / "a", _TEMPLATE_SCHEMA)
    judge_cli = _run_rubric(tmp_path / "b", _JUDGE_CLI_SCHEMA)
    assert template == judge_cli


def test_rubric_per_criterion_schema_earns_partial_credit(tmp_path):
    """The half that regressed: one of two positive criteria met, no trap hit.

    Pinned rather than compared, so a future change that makes both schemas
    agree on the wrong number still fails. 2 of 4 positive weight, no penalty.
    """
    assert _run_rubric(tmp_path, _JUDGE_CLI_SCHEMA) == 0.5


def test_rubric_negative_criterion_penalises_only_when_hit(tmp_path):
    """satisfied=true on an is_positive=false criterion means the trap was hit.

    The judge prompt now states this explicitly. An agent that avoided the trap
    must not be penalised for it, which is what scored a clean run to zero.
    """
    hit = dict(_JUDGE_CLI_SCHEMA, per_criterion=[
        {"number": 1, "satisfied": True}, {"number": 2, "satisfied": False},
        {"number": 3, "satisfied": True},
    ])
    assert _run_rubric(tmp_path, hit) < _run_rubric(tmp_path / "clean", _JUDGE_CLI_SCHEMA)
