"""Regression tests for the MCP-Atlas -> Harbor adapter.

Every assertion here corresponds to a defect that shipped undetected because
`adapters/mcp_atlas/` had no tests at all. The adapter imports its shared
templates from services/mcp_eval/convert_tasks_to_harbor.py but defines its
own task.toml / Dockerfile / compose templates, and those three drifted:
bundles came out with no MCP servers, no tool allowlist, and no `main`
service, so `harbor run` could never start an agent.

Keep these tests structural (no Docker, no network) so they run in CI on
every change to the adapter.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

try:  # 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.10 and older
    tomllib = None  # type: ignore[assignment]

import yaml

ADAPTER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ADAPTER_DIR.parents[1]


def _load_adapter():
    """Import adapter.py by path.

    It lives in a hyphen-free package but is normally imported as a
    sibling module by run_adapter.py, which puts its own directory on
    sys.path. Do the same here rather than depending on how pytest happens
    to have set rootdir.
    """
    sys.path.insert(0, str(ADAPTER_DIR))
    spec = importlib.util.spec_from_file_location("mcp_atlas_adapter", ADAPTER_DIR / "adapter.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register before exec: @dataclass resolves annotations via
    # sys.modules[cls.__module__], which fails for a module that isn't there.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


adapter = _load_adapter()

requires_toml = pytest.mark.skipif(tomllib is None, reason="tomllib requires Python 3.11+")

CLAIMS = [
    'The answer mentions "xCG: Explainable Cell Graphs"',
    "The response includes the Spanish translation",
]
TOOLS = ["arxiv_search_papers", "lara-translate_translate", "whois_whois_domain"]


@pytest.fixture()
def record():
    return adapter.MCPAtlasRecord(
        task_id="sample-task",
        prompt='Find the study "X" and translate it.\nSecond line.',
        gtfa_claims=list(CLAIMS),
        enabled_tools=list(TOOLS),
    )


@pytest.fixture()
def bundle(tmp_path, record):
    gen = adapter.MCPAtlasToHarbor(out_root=tmp_path)
    return gen.generate_task(record)


def _toml(bundle: Path) -> dict:
    return tomllib.loads((bundle / "task.toml").read_text())


# --- bundle layout ---------------------------------------------------------


def test_bundle_has_every_required_file(bundle):
    for rel in (
        "task.toml",
        "instruction.md",
        "solution/solve.sh",
        "tests/test.sh",
        "tests/agent_judge.py",
        "environment/Dockerfile",
        "environment/docker-compose.yaml",
        "environment/enabled_tools.txt",
        f"environment/{adapter.BRIDGE_FILENAME}",
    ):
        assert (bundle / rel).is_file(), f"missing {rel}"


def test_solve_and_test_scripts_are_executable(bundle):
    for rel in ("solution/solve.sh", "tests/test.sh"):
        assert (bundle / rel).stat().st_mode & 0o111, f"{rel} is not executable"


# --- G05 / G04: schema version and agent timeout ---------------------------


@requires_toml
def test_targets_current_harbor_schema(bundle):
    assert _toml(bundle)["schema_version"] == "1.3"


@requires_toml
def test_agent_timeout_uses_schema_13_key(bundle):
    """`timeout` is the 1.0 key. On 1.3 it is silently dropped, and the task
    falls back to the default agent timeout instead of the configured one."""
    agent = _toml(bundle)["agent"]
    assert "timeout" not in agent, "1.0-era key would be dropped by Harbor"
    assert agent["timeout_sec"] == adapter.DEFAULT_AGENT_TIMEOUT


# --- G01: the agent must actually get MCP tools ----------------------------


@requires_toml
def test_declares_an_mcp_server(bundle):
    servers = _toml(bundle)["environment"]["mcp_servers"]
    assert servers, "no mcp_servers: the agent would run with zero tools"
    (server,) = servers
    assert server["transport"] == "stdio"
    assert server["command"] == "uv"
    assert f"{adapter.BRIDGE_DIR}/{adapter.BRIDGE_FILENAME}" in server["args"]


def test_bridge_is_staged_verbatim(bundle):
    """The bundle's copy must match the repo module, or a fix to the bridge
    silently fails to reach generated tasks."""
    staged = (bundle / "environment" / adapter.BRIDGE_FILENAME).read_text()
    source = (ADAPTER_DIR / adapter.BRIDGE_FILENAME).read_text()
    assert staged == source


# --- G02: per-task tool allowlist ------------------------------------------


def test_enabled_tools_are_written(bundle):
    written = (bundle / "environment" / "enabled_tools.txt").read_text().split()
    assert written == TOOLS


def test_enabled_tools_are_copied_into_the_image(bundle):
    dockerfile = (bundle / "environment" / "Dockerfile").read_text()
    assert f"COPY enabled_tools.txt {adapter.ENABLED_TOOLS_PATH}" in dockerfile


@requires_toml
def test_bridge_is_pointed_at_the_allowlist(bundle):
    env = _toml(bundle)["environment"]["env"]
    assert env["ENABLED_TOOLS_FILE"] == adapter.ENABLED_TOOLS_PATH
    assert env["MCP_SERVER_URL"].endswith(str(adapter.DEFAULT_SANDBOX_PORT))


def test_empty_allowlist_produces_an_empty_file(tmp_path):
    """A task with no tool scoping must still emit the file (the bridge treats
    a blank allowlist as 'no allowlist'), not omit it."""
    rec = adapter.MCPAtlasRecord(task_id="t", prompt="p", gtfa_claims=[], enabled_tools=[])
    out = adapter.MCPAtlasToHarbor(out_root=tmp_path).generate_task(rec)
    assert (out / "environment" / "enabled_tools.txt").read_text() == ""


# --- G03: Harbor runs the agent in the `main` service ----------------------


def test_compose_defines_main_and_sidecar(bundle):
    services = yaml.safe_load((bundle / "environment" / "docker-compose.yaml").read_text())["services"]
    assert "main" in services, "Harbor runs the agent in the service named 'main'"
    assert "mcp-server" in services
    assert services["main"]["depends_on"] == ["mcp-server"]


def test_main_service_builds_the_agent_image(bundle):
    services = yaml.safe_load((bundle / "environment" / "docker-compose.yaml").read_text())["services"]
    assert services["main"]["build"]["dockerfile"] == "Dockerfile"


# --- G06: the healthcheck has to detect an unhealthy sandbox ---------------


@requires_toml
def test_healthcheck_inspects_the_response_body(bundle):
    """/health returns HTTP 200 even when the MCP client is down -- it reports
    failure in the body -- so a bare `curl -sf` passes against a dead sandbox."""
    command = _toml(bundle)["environment"]["healthcheck"]["command"]
    assert "health_and_client_connection_ok" in command
    assert "/health" in command


# --- G11: the oracle must be gradeable -------------------------------------


def test_oracle_emits_a_judge_readable_trajectory(bundle, tmp_path):
    """agent_judge.py reads /logs/agent/*.txt and keeps the last line whose
    JSON has type == "result". The old `echo "no solution"` oracle wrote
    nothing there, so the judge raised and the oracle gate failed by
    construction."""
    solve = (bundle / "solution" / "solve.sh").read_text()
    logs = tmp_path / "logs" / "agent"
    logs.mkdir(parents=True)
    # Run the oracle's payload with /logs redirected into the tmp dir.
    script = solve.replace("/logs/agent", str(logs))
    subprocess.run(["bash", "-c", script], check=True, capture_output=True)

    written = list(logs.glob("*.txt"))
    assert written, "oracle wrote no trajectory for the judge to read"

    response = ""
    for line in written[0].read_text().splitlines():
        event = json.loads(line)
        if event.get("type") == "result" and event.get("result"):
            response = event["result"]
    assert response, "judge would extract an empty agent response"
    for claim in CLAIMS:
        assert claim in response


def test_oracle_handles_a_task_with_no_claims(tmp_path):
    rec = adapter.MCPAtlasRecord(task_id="t", prompt="p", gtfa_claims=[], enabled_tools=[])
    out = adapter.MCPAtlasToHarbor(out_root=tmp_path).generate_task(rec)
    logs = tmp_path / "logs" / "agent"
    logs.mkdir(parents=True)
    script = (out / "solution" / "solve.sh").read_text().replace("/logs/agent", str(logs))
    subprocess.run(["bash", "-c", script], check=True, capture_output=True)
    assert list(logs.glob("*.txt"))


# --- G08 / G10: registry metadata and network policy -----------------------


@requires_toml
def test_package_metadata_is_populated(bundle):
    task = _toml(bundle)["task"]
    assert task["name"] == f"{adapter.DEFAULT_ORG}/sample-task"
    assert task["description"], "empty description blocks `harbor publish`"
    assert "mcp" in task["keywords"]


@requires_toml
def test_network_mode_is_explicit(bundle):
    assert _toml(bundle)["environment"]["network_mode"] == adapter.DEFAULT_NETWORK_MODE


# --- escaping / robustness -------------------------------------------------


@requires_toml
def test_prompt_with_toml_metacharacters_stays_parseable(tmp_path):
    rec = adapter.MCPAtlasRecord(
        task_id="quoted",
        prompt='He said "hello"\tand\\or left.\nNew line.',
        gtfa_claims=['a "quoted" claim'],
        enabled_tools=[],
    )
    out = adapter.MCPAtlasToHarbor(out_root=tmp_path).generate_task(rec)
    parsed = tomllib.loads((out / "task.toml").read_text())
    assert parsed["task"]["description"]
    assert "\n" not in parsed["task"]["description"]


def test_generate_task_is_idempotent_without_overwrite(tmp_path, record):
    gen = adapter.MCPAtlasToHarbor(out_root=tmp_path)
    first = gen.generate_task(record)
    (first / "task.toml").write_text("sentinel")
    gen.generate_task(record)
    assert (first / "task.toml").read_text() == "sentinel"
    gen.generate_task(record, overwrite=True)
    assert (first / "task.toml").read_text() != "sentinel"


def test_generate_many_respects_limit_and_ids(tmp_path):
    records = [
        adapter.MCPAtlasRecord(task_id=f"t{i}", prompt="p", gtfa_claims=[], enabled_tools=[])
        for i in range(5)
    ]
    gen = adapter.MCPAtlasToHarbor(out_root=tmp_path)
    assert len(gen.generate_many(iter(records), limit=2)) == 2

    shutil.rmtree(tmp_path)
    gen = adapter.MCPAtlasToHarbor(out_root=tmp_path)
    picked = gen.generate_many(iter(records), ids={"t3"})
    assert [p.name for p in picked] == ["t3"]


# --- task data: mounted where the tools can actually see it ----------------


@pytest.fixture()
def data_bundle(tmp_path):
    data = tmp_path / "src_data"
    (data / "nested").mkdir(parents=True)
    (data / "input.csv").write_text("a,b\n1,2\n")
    (data / "nested" / "extra.json").write_text("{}")
    rec = adapter.MCPAtlasRecord(
        task_id="with-data", prompt="p", gtfa_claims=["c"], enabled_tools=["t"], data_dir=data
    )
    return adapter.MCPAtlasToHarbor(out_root=tmp_path / "out").generate_task(rec)


def test_data_files_are_copied_into_the_bundle(data_bundle):
    staged = data_bundle / "environment" / "task_data"
    assert (staged / "input.csv").read_text() == "a,b\n1,2\n"
    assert (staged / "nested" / "extra.json").is_file(), "nested data was not copied"


def test_data_is_mounted_on_the_sidecar_not_the_agent(data_bundle):
    """The MCP servers run in `mcp-server`, so data mounted into `main` would
    sit somewhere no tool can read."""
    services = yaml.safe_load((data_bundle / "environment" / "docker-compose.yaml").read_text())["services"]
    volumes = services["mcp-server"].get("volumes") or []
    assert any(adapter.TASK_DATA_PATH in v for v in volumes), f"not mounted on sidecar: {volumes}"
    assert not services["main"].get("volumes"), "data mounted on the agent container is unreachable"


def test_data_is_mounted_under_the_filesystem_server_root(data_bundle):
    """The filesystem server is rooted at /data and desktop-commander's
    allowedDirectories is set to ["/data"]; anything outside is invisible."""
    assert adapter.TASK_DATA_PATH.startswith("/data/")
    assert adapter.TASK_OUTPUT_PATH.startswith("/data/")


def test_data_is_mounted_read_only(data_bundle):
    services = yaml.safe_load((data_bundle / "environment" / "docker-compose.yaml").read_text())["services"]
    (volume,) = services["mcp-server"]["volumes"]
    assert volume.endswith(":ro"), "a task that can rewrite its own fixtures can grade itself"


def test_task_without_data_mounts_nothing(bundle):
    services = yaml.safe_load((bundle / "environment" / "docker-compose.yaml").read_text())["services"]
    assert not services["mcp-server"].get("volumes")
    assert not (bundle / "environment" / "task_data").exists()


def test_missing_data_dir_fails_loudly(tmp_path):
    rec = adapter.MCPAtlasRecord(
        task_id="t", prompt="p", gtfa_claims=[], enabled_tools=[], data_dir=tmp_path / "nope"
    )
    with pytest.raises(FileNotFoundError):
        adapter.MCPAtlasToHarbor(out_root=tmp_path / "out").generate_task(rec)


# --- artifacts: collected from the container the files land in -------------


@requires_toml
def test_agent_outputs_are_collected_from_the_sidecar(bundle):
    (artifact,) = _toml(bundle)["artifacts"]
    assert artifact["source"] == adapter.TASK_OUTPUT_PATH
    assert artifact["service"] == "mcp-server", (
        "tools run in the sidecar, so collecting from `main` yields an empty directory"
    )


# --- manifest loading ------------------------------------------------------


def test_data_dir_resolves_against_the_manifest_not_the_cwd(tmp_path, monkeypatch):
    manifest_dir = tmp_path / "task"
    (manifest_dir / "data").mkdir(parents=True)
    (manifest_dir / "data" / "f.txt").write_text("x")
    manifest = manifest_dir / "task.jsonl"
    manifest.write_text(json.dumps({
        "TASK": "rel", "PROMPT": "p", "GTFA_CLAIMS": ["c"],
        "ENABLED_TOOLS": ["t"], "DATA_DIR": "data",
    }) + "\n")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    (record,) = list(adapter.MCPAtlasLoader(source=manifest))
    assert record.data_dir == manifest_dir / "data"
    assert record.enabled_tools == ["t"]


# --- task-authored grading files -------------------------------------------


TASK_TESTS = {
    "test_outputs.py": "def test_x():\n    assert True\n",
    "test_weights.json": json.dumps({
        "components": {"traj_tests": {"weight": 1, "tests": {"test_x": 1}}, "rubric": {"weight": 1}}
    }),
    "rubric.json": json.dumps([{"id": "claim_000", "text": "c", "weight": 2, "is_positive": True}]),
}


@pytest.fixture()
def graded_bundle(tmp_path):
    tests = tmp_path / "task_tests"
    tests.mkdir()
    for name, body in TASK_TESTS.items():
        (tests / name).write_text(body)
    rec = adapter.MCPAtlasRecord(
        task_id="graded", prompt="p", gtfa_claims=["c"], enabled_tools=["t"], tests_dir=tests
    )
    return adapter.MCPAtlasToHarbor(out_root=tmp_path / "out").generate_task(rec)


def test_task_grading_files_override_the_stubs(graded_bundle):
    """The generated stubs ship inert; a task's own files must win, or its
    real tests are silently replaced by an empty stub."""
    assert (graded_bundle / "tests" / "test_outputs.py").read_text() == TASK_TESTS["test_outputs.py"]
    weights = json.loads((graded_bundle / "tests" / "test_weights.json").read_text())
    assert weights["components"]["traj_tests"]["weight"] == 1, "task weights were overwritten by the inert stub"


def test_shipping_grading_files_selects_the_weighted_verifier(graded_bundle):
    """Without --weighted the plain test.sh runs only agent_judge.py, so the
    task's Channel A tests would never execute."""
    assert "weighted_judge_entry.py" in (graded_bundle / "tests" / "test.sh").read_text()


def test_weighted_bundle_ships_every_scoring_module(graded_bundle):
    for name in ("traj_asserts.py", "weighted_judge.py", "rubric_weighted.py", "weighted_judge_entry.py"):
        assert (graded_bundle / "tests" / name).is_file(), f"missing {name}"


def test_shipped_scoring_modules_match_the_repo(graded_bundle):
    for name in ("traj_asserts.py", "weighted_judge.py", "rubric_weighted.py"):
        staged = (graded_bundle / "tests" / name).read_text()
        source = (REPO_ROOT / "services" / "scoring" / name).read_text()
        assert staged == source, f"{name} is stale in the bundle"


def test_missing_tests_dir_fails_loudly(tmp_path):
    rec = adapter.MCPAtlasRecord(
        task_id="t", prompt="p", gtfa_claims=[], enabled_tools=[], tests_dir=tmp_path / "nope"
    )
    with pytest.raises(FileNotFoundError):
        adapter.MCPAtlasToHarbor(out_root=tmp_path / "out").generate_task(rec)


# --- the oracle replays a reference trajectory -----------------------------


ORACLE_CALLS = [
    {"name": "filesystem_read_text_file", "arguments": {"path": "/data/task_data/in.csv"},
     "result": "a,b"},
    {"name": "filesystem_write_file", "arguments": {"path": "/data/outputs/report.json"},
     "result": "written"},
]


def _replay_oracle(bundle: Path, tmp_path: Path) -> list[dict]:
    logs = tmp_path / "logs" / "agent"
    logs.mkdir(parents=True, exist_ok=True)
    script = (bundle / "solution" / "solve.sh").read_text().replace("/logs/agent", str(logs))
    subprocess.run(["bash", "-c", script], check=True, capture_output=True)
    messages = []
    for line in next(iter(logs.glob("*.txt"))).read_text().splitlines():
        event = json.loads(line)
        if event.get("type") == "message" and event.get("message"):
            messages.append(event["message"])
    return messages


def test_oracle_replays_the_reference_tool_calls(tmp_path):
    """Channel A grades tool calls, so an oracle that only states an answer
    scores zero there however correct the answer is."""
    rec = adapter.MCPAtlasRecord(
        task_id="oracle-traj", prompt="p", gtfa_claims=["c"], enabled_tools=["t"],
        oracle_tool_calls=list(ORACLE_CALLS),
    )
    bundle = adapter.MCPAtlasToHarbor(out_root=tmp_path / "out").generate_task(rec)
    messages = _replay_oracle(bundle, tmp_path)

    names = [
        tc["function"]["name"]
        for m in messages for tc in (m.get("tool_calls") or [])
    ]
    assert names == [c["name"] for c in ORACLE_CALLS]

    # Arguments must survive as a JSON string, the shape traj_asserts parses.
    first = next(tc for m in messages for tc in (m.get("tool_calls") or []))
    assert json.loads(first["function"]["arguments"])["path"] == "/data/task_data/in.csv"

    # Every call needs a matching tool result, or tool_errored() and result
    # lookups have nothing to bind to.
    tool_ids = {m["tool_call_id"] for m in messages if m.get("role") == "tool"}
    assert tool_ids == {tc["id"] for m in messages for tc in (m.get("tool_calls") or [])}


def test_oracle_without_tool_calls_still_answers(tmp_path):
    rec = adapter.MCPAtlasRecord(
        task_id="no-calls", prompt="p", gtfa_claims=["only claim"], enabled_tools=[]
    )
    bundle = adapter.MCPAtlasToHarbor(out_root=tmp_path / "out").generate_task(rec)
    messages = _replay_oracle(bundle, tmp_path)
    assert not any(m.get("tool_calls") for m in messages)
    assert any("only claim" in (m.get("content") or "") for m in messages)


def test_malformed_oracle_calls_are_ignored_not_fatal(tmp_path):
    """A bad oracle should cost the oracle its Channel A credit, not stop the
    bundle from rendering."""
    loader = adapter.MCPAtlasLoader(source=None)
    assert loader._make_record("t", "p", [], oracle_tool_calls_raw="not json").oracle_tool_calls == []
    assert loader._make_record("t", "p", [], oracle_tool_calls_raw=[{"no": "name"}]).oracle_tool_calls == []
    assert loader._make_record(
        "t", "p", [], oracle_tool_calls_raw='[{"name": "x"}]'
    ).oracle_tool_calls == [{"name": "x"}]


# --- credentials reach the verifier ----------------------------------------


@requires_toml
def test_verifier_env_forwards_the_judge_backend(bundle):
    """The rubric judge shells out to the local `codex` CLI, so JUDGE_MODEL is
    the whole judge configuration. The bridge names it used to need
    (EVAL_LLM_BASE_URL, EVAL_LLM_API_KEY) are read by nothing and must stay
    dropped: an env var that looks like judge configuration, and is not, is
    how a run ends up pointed somewhere nobody intended."""
    env = _toml(bundle)["verifier"]["env"]
    assert env["JUDGE_MODEL"] == adapter.DEFAULT_JUDGE_MODEL
    for key in ("EVAL_LLM_BASE_URL", "EVAL_LLM_API_KEY"):
        assert key not in env, f"verifier env still forwards the dead {key}"


@requires_toml
def test_verifier_env_forwards_no_dead_claude_credentials(bundle):
    """The judge stopped driving claude-agent-sdk, so nothing in the verifier
    reads these. Left in place they would look like judge configuration while
    configuring nothing, which is how a run ends up pointed somewhere nobody
    intended."""
    env = _toml(bundle)["verifier"]["env"]
    for dead in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
                 "CLAUDE_CODE_OAUTH_TOKEN", "LITELLM_API_KEY", "LITELLM_BASE_URL"):
        assert dead not in env, f"verifier env still forwards dead {dead}"


# --- G21: solve.sh must be silent (Harbor captures stdout+stderr into oracle.txt)
def test_oracle_solve_sh_is_silent_and_trajectory_intact(tmp_path):
    """Harbor's oracle agent runs solve.sh with stdout AND stderr redirected to
    /logs/agent/oracle.txt -- the same file the script writes the trajectory
    into -- through a second fd positioned at offset 0. Any status line the
    script prints overwrites the head of the first JSON event (in the xenon
    task that was the wikipedia call), so Channel A silently loses a credited
    test and the oracle can never reach 1.0. The script must print nothing,
    and every line of the trajectory it writes must be valid JSON."""
    rec = adapter.MCPAtlasRecord(
        task_id="t", prompt="p", gtfa_claims=["c1"], enabled_tools=["search"],
        oracle_tool_calls=[{"name": "search", "arguments": {"q": "x"}, "result": "r"}],
    )
    out = adapter.MCPAtlasToHarbor(out_root=tmp_path).generate_task(rec)
    logs = tmp_path / "logs" / "agent"
    logs.mkdir(parents=True)
    script = (out / "solution" / "solve.sh").read_text().replace("/logs/agent", str(logs))
    proc = subprocess.run(["bash", "-c", script], check=True, capture_output=True, text=True)
    assert proc.stdout == "" and proc.stderr == "", (proc.stdout, proc.stderr)
    lines = (logs / "oracle.txt").read_text().splitlines()
    assert lines, "oracle wrote no trajectory"
    events = [json.loads(l) for l in lines if l.strip()]
    names = [tc["function"]["name"]
             for e in events for tc in ((e.get("message") or {}).get("tool_calls") or [])]
    assert names == ["search"]
