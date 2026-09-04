from __future__ import annotations

import ast
import csv
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

_MEVAL = Path(__file__).parent.parent.parent / "services" / "mcp_eval"
sys.path.insert(0, str(_MEVAL))
from convert_tasks_to_harbor import (  # noqa: E402
    AGENT_JUDGE_TEMPLATE,
    TEST_OUTPUTS_PY_STUB,
    TEST_SH,
    TEST_WEIGHTS_JSON_STUB,
    WEIGHTED_JUDGE_ENTRY_TEMPLATE,
    WEIGHTED_TEST_SH,
    _read_scoring_module_source,
)

csv.field_size_limit(sys.maxsize)

DEFAULT_IMAGE = "ghcr.io/scaleapi/mcp-atlas:1.2.7"
DEFAULT_CATEGORY = "mcp-tool-use"
# The judge grades on a Codex subscription through the local `codex` CLI.
# This is the judge model only; the agent under test is selected separately.
DEFAULT_JUDGE_MODEL = "gpt-5.6-sol"
DEFAULT_AGENT_TIMEOUT = 1800
DEFAULT_SANDBOX_PORT = 1984
DEFAULT_ORG = "mcp-atlas"
# The agent needs egress: MCP-Atlas tasks call live third-party APIs (arxiv,
# whois, clinicaltrials.gov, ...) through the sandbox sidecar.
DEFAULT_NETWORK_MODE = "public"

# Harbor task schema this adapter targets. `harbor task init` on the 0.20.x
# CLI emits 1.3; emitting the old "1.0" shape meant Harbor silently migrated
# the file at load time, and `[agent] timeout` (a 1.0 key) was dropped on the
# way to 1.3's `timeout_sec` -- every task quietly fell back to the default
# agent timeout instead of the 1800s this adapter intended.
HARBOR_SCHEMA_VERSION = "1.3"

# Where the bundle stages the REST->MCP bridge inside the agent container.
BRIDGE_DIR = "/opt/mcp-bridge"
BRIDGE_FILENAME = "mcp_rest_bridge.py"
ENABLED_TOOLS_PATH = "/enabled_tools.txt"

# Where a task's data files land inside the SIDECAR. This must sit under
# /data: the sandbox's MCP servers run in the mcp-server container, not in
# the agent's, and both the filesystem server (rooted at /data, see
# mcp_server_template.json) and desktop-commander (allowedDirectories set to
# ["/data"] at startup, see agent_environment/main.py::lifespan) are blind to
# anything outside it. Mounting task data into `main` would put it somewhere
# no tool can read.
TASK_DATA_PATH = "/data/task_data"
# Where the agent is told to write results, and what gets collected back.
TASK_OUTPUT_PATH = "/data/outputs"

# The agent container. It does NOT run the MCP servers -- those live in the
# `mcp-server` sidecar (see DOCKER_COMPOSE_TEMPLATE). This image only needs
# curl (healthcheck) and uv (to run the stdio bridge with its inline deps).
DOCKERFILE_TEMPLATE = """\
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \\
    && rm -rf /var/lib/apt/lists/*

# Pre-resolve the bridge's inline dependencies at build time so the agent
# does not pay a package download on its first tool call (and so the task
# still starts on a network-restricted runner).
COPY {bridge_filename} {bridge_dir}/{bridge_filename}
COPY enabled_tools.txt {enabled_tools_path}
RUN uv run --no-project {bridge_dir}/{bridge_filename} --help >/dev/null 2>&1 || true
"""

# Harbor runs the agent in the service named `main` (harbor.constants.
# MAIN_SERVICE_NAME) and collects artifacts from it. A compose file without a
# `main` service brings up sidecars and no agent at all, which is what the
# previous single-service template did.
DOCKER_COMPOSE_TEMPLATE = """\
services:
  main:
    build:
      context: .
      dockerfile: Dockerfile
    depends_on:
      - mcp-server
    command: ["sleep", "infinity"]

  mcp-server:
    image: {image}
    expose:
      - "{sandbox_port}"
{sidecar_volumes}"""

# Mounted read-only: the task's inputs are evidence, and a task that can
# rewrite its own fixtures can score against data it authored itself.
SIDECAR_VOLUMES_TEMPLATE = """\
    volumes:
      - ./task_data:{task_data_path}:ro
"""

# The sandbox's /health always returns HTTP 200 -- it encodes failure in the
# body (`health_and_client_connection_timeout` /
# `..._health_check_failed`, see agent_environment/main.py::health). A bare
# `curl -sf` therefore reports a dead sandbox as healthy, so the check must
# match on the success status string.
HEALTHCHECK_COMMAND = (
    "curl -sf --max-time 10 http://mcp-server:{sandbox_port}/health "
    "| grep -q health_and_client_connection_ok"
)

# {{VAR}} → ${VAR} after .format(); Harbor expands ${VAR:-} at runtime.
TASK_TOML_TEMPLATE = """\
schema_version = "{schema_version}"

[task]
name = "{package_name}"
description = "{description}"
keywords = ["mcp", "tool-use", "agentic"]

[metadata]
category = "{category}"
task_id = "{task_id}"
image = "{image}"
source = "ScaleAI/MCP-Atlas"

[agent]
timeout_sec = {agent_timeout}

[environment]
cpus = 4
memory_mb = 10240
storage_mb = 10240
network_mode = "{network_mode}"

# The mcp-atlas image speaks a bespoke REST API, not MCP (see
# adapters/mcp_atlas/mcp_rest_bridge.py). The agent therefore talks to a
# stdio bridge running in its own container, which proxies to the sidecar.
[[environment.mcp_servers]]
name = "mcp-atlas"
transport = "stdio"
command = "uv"
args = ["run", "--no-project", "{bridge_dir}/{bridge_filename}"]

# Gate the agent launch until the sandbox sidecar has finished starting its
# MCP servers. Without this the agent connects to a bridge whose upstream
# isn't up yet and runs with zero tools.
[environment.healthcheck]
command = "{healthcheck_command}"
interval_sec = 5
timeout_sec = 15
start_period_sec = 180
retries = 36

[environment.env]
MCP_SERVER_URL = "http://mcp-server:{sandbox_port}"
ENABLED_TOOLS_FILE = "{enabled_tools_path}"

[verifier]
timeout_sec = 900.0

[verifier.env]
# The rubric judge shells out to the local `codex` CLI from
# services/scoring/rubric_judge_cli.py. It no longer reaches any endpoint, so
# the bridge names this block used to forward (EVAL_LLM_BASE_URL,
# EVAL_LLM_API_KEY) are read by nothing in the verifier and are dropped rather
# than left in place: an env var that looks like it configures the judge, and
# does not, is how a run ends up pointed somewhere nobody intended.
#
# JUDGE_MODEL is the one name still consulted. Note the CLI transport means
# rubric grading needs `codex` installed and logged in wherever the judge
# actually runs — inside a container that lacks it, the judge's preflight
# fails fast and the rubric channel is graded host-side instead.
# See harness/CODEX-JUDGE.md.
JUDGE_MODEL = "{judge_model}"
{artifacts}"""

# Whatever the agent wrote. `service` is required because the tools run in
# the sidecar, so the files land there and not in the agent's container --
# the default (`main`) would collect an empty directory.
ARTIFACTS_TEMPLATE = """
[[artifacts]]
source = "{task_output_path}"
destination = "agent_outputs"
service = "mcp-server"
"""

# The oracle. `harbor run --agent oracle` runs this instead of a model, and
# the bundle only passes review if that run scores 1.0.
#
# The judge (tests/agent_judge.py) grades whatever it finds in /logs/agent/
# *.txt, reading the last `{{"type": "result", "result": ...}}` line. A
# reference solution therefore has to leave a trajectory there; the previous
# `echo "no solution"` stub left the directory empty, the judge raised
# "No trajectory .txt files found", and the oracle gate failed by
# construction on every task.
#
# For a claims-coverage benchmark the reference answer IS the set of
# ground-truth claims: the judge asks "does the response satisfy each
# claim?", so an oracle that states all of them is the correct upper bound.
SOLVE_SH_TEMPLATE = """#!/bin/bash
# Oracle solution: replay the reference trajectory so the verifier grades a
# perfect run. See adapters/mcp_atlas/adapter.py.
set -euo pipefail

mkdir -p /logs/agent

python3 - <<'PYEOF' > /logs/agent/oracle.txt
import json

claims = {claims_json}
tool_calls = {oracle_tool_calls_json}

# Channel A reads tool calls off the trajectory, so an oracle that only
# states an answer scores zero there no matter how correct the answer is.
# Replaying the reference tool sequence makes the oracle a true upper bound
# across both channels instead of only the rubric.
for i, call in enumerate(tool_calls):
    call_id = "oracle_call_%d" % i
    print(json.dumps({{"type": "message", "message": {{
        "role": "assistant",
        "content": call.get("rationale", ""),
        "tool_calls": [{{
            "id": call_id,
            "type": "function",
            "function": {{
                "name": call["name"],
                "arguments": json.dumps(call.get("arguments", {{}})),
            }},
        }}],
    }}}}))
    print(json.dumps({{"type": "message", "message": {{
        "role": "tool",
        "tool_call_id": call_id,
        "content": call.get("result", "ok"),
    }}}}))

answer = "\\n".join(f"- {{c}}" for c in claims) if claims else "No ground-truth claims for this task."
print(json.dumps({{"type": "message", "message": {{"role": "assistant", "content": answer}}}}))
print(json.dumps({{"type": "result", "result": answer}}))
PYEOF

# Deliberately silent. Harbor's oracle agent runs this script with BOTH stdout
# and stderr redirected into the very same /logs/agent/oracle.txt, through a
# separate fd positioned at offset 0 -- so any status line printed here would
# overwrite the head of the trajectory written above (see G21).
"""


def _toml_escape(s: str) -> str:
    out: list[str] = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def _parse_claims(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(c).strip() for c in raw if str(c).strip()]
    if not isinstance(raw, str):
        return []
    raw = raw.strip()
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(c).strip() for c in parsed if str(c).strip()]
        except json.JSONDecodeError:
            pass
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list):
                return [str(c).strip() for c in parsed if str(c).strip()]
        except (ValueError, SyntaxError):
            pass
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _claims_to_rubrics(claims: list[str]) -> list[dict]:
    return [
        {"id": f"claim_{i:03d}", "title": c, "description": c}
        for i, c in enumerate(claims)
    ]


def _claims_to_weighted_rubric(claims: list[str]) -> list[dict]:
    """rubric_weighted.parse_rubric()-compatible shape for tests/rubric.json:
    every existing GTFA claim carried over as a goal criterion (weight=1,
    is_positive=True) -- same claims agent_judge.py already grades, so a
    task's Channel B behaves the same whether graded by agent_judge.py alone
    or (once opted in) folded into the weighted ledger."""
    return [
        {"id": f"claim_{i:03d}", "text": c, "weight": 1, "is_positive": True}
        for i, c in enumerate(claims)
    ]


def _parse_oracle_calls(raw) -> list[dict]:
    """The oracle's reference tool sequence, from a manifest field.

    Accepts a list of objects or a JSON string (CSV manifests can only carry
    strings). Anything that isn't a list of objects is treated as absent
    rather than raising -- a malformed oracle should cost the oracle its
    Channel A credit, not stop the whole bundle from rendering.
    """
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [c for c in raw if isinstance(c, dict) and c.get("name")]


def _parse_multimodal(raw) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _read_bridge_source() -> str:
    """Source of the REST->MCP bridge staged into each bundle.

    Read off disk rather than inlined as a template string so the bridge stays
    a real, importable, testable module instead of a quoted blob -- the same
    reason convert_tasks_to_harbor.py embeds the scoring modules this way.
    """
    return (Path(__file__).parent / BRIDGE_FILENAME).read_text(encoding="utf-8")


def _describe(record: MCPAtlasRecord) -> str:
    """One-line package description for `[task].description`.

    Harbor's registry surfaces this; an empty string blocks `harbor publish`.
    Built from the prompt's first line, truncated, with newlines flattened so
    it stays a single TOML basic string.
    """
    first_line = record.prompt.strip().splitlines()[0] if record.prompt.strip() else ""
    summary = " ".join(first_line.split())
    if len(summary) > 160:
        summary = summary[:157].rstrip() + "..."
    return summary or f"MCP-Atlas tool-use task {record.task_id}"


def _sanitize_id(task_id: str) -> str:
    s = task_id.lower().strip()
    s = re.sub(r"[^a-z0-9\-_]", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "task"


@dataclass
class MCPAtlasRecord:
    task_id: str
    prompt: str
    gtfa_claims: list[str]
    enabled_tools: list[str]
    # Directory of input files the task operates on. Copied into the bundle
    # and mounted read-only into the sidecar at TASK_DATA_PATH. None for the
    # plain dataset rows, which are pure text-in/text-out.
    data_dir: Path | None = None
    # Directory of task-authored grading files (test_outputs.py,
    # test_weights.json, rubric.json). Copied over the generated defaults, so
    # a task ships real Channel A tests and a weighted rubric instead of the
    # inert stubs. Implies weighted grading.
    tests_dir: Path | None = None
    # The reference tool sequence the oracle replays, as
    # [{"name", "arguments", "result", "rationale"}]. Without it the oracle
    # makes no tool calls and scores zero on Channel A.
    oracle_tool_calls: list[dict] = field(default_factory=list)
    # Optional multimodal attachments: [{type, path}] where type is "image" or
    # "audio" and path is relative to the task data directory. Written to
    # environment/multimodal.json so harnesses can inject them as content parts.
    multimodal: list[dict] = field(default_factory=list)


class MCPAtlasLoader:
    def __init__(
        self,
        source: str | Path | None = None,
        tool_map: dict[str, list[str]] | None = None,
    ) -> None:
        self._source = source
        self._tool_map: dict[str, list[str]] = tool_map or {}
        self._base_dir = Path(source).parent if source is not None else None

    def __iter__(self) -> Iterator[MCPAtlasRecord]:
        if self._source is None:
            yield from self._load_hf()
        else:
            p = Path(self._source)
            if p.suffix == ".csv":
                yield from self._load_csv(p)
            elif p.suffix in (".jsonl", ".ndjson"):
                yield from self._load_jsonl(p)
            elif p.suffix == ".parquet":
                yield from self._load_parquet(p)
            else:
                raise ValueError(f"Unsupported source format: {p.suffix!r}")

    def _make_record(
        self,
        raw_id: str,
        prompt: str,
        claims_raw,
        tools_raw=None,
        data_dir_raw=None,
        tests_dir_raw=None,
        oracle_tool_calls_raw=None,
        multimodal_raw=None,
    ) -> MCPAtlasRecord:
        safe_id = _sanitize_id(raw_id)
        claims = _parse_claims(claims_raw)
        if tools_raw is not None:
            tools = _parse_claims(tools_raw) if isinstance(tools_raw, str) else list(tools_raw)
        else:
            tools = self._tool_map.get(raw_id, self._tool_map.get(safe_id, []))
        # Resolved against the manifest's own directory, not the process cwd,
        # so a task is relocatable and `--input` works from anywhere.
        def _resolve(raw):
            if not raw:
                return None
            candidate = Path(str(raw))
            if not candidate.is_absolute() and self._base_dir is not None:
                candidate = self._base_dir / candidate
            return candidate

        data_dir = _resolve(data_dir_raw)
        tests_dir = _resolve(tests_dir_raw)
        return MCPAtlasRecord(
            task_id=safe_id,
            prompt=prompt,
            gtfa_claims=claims,
            enabled_tools=tools,
            data_dir=data_dir,
            tests_dir=tests_dir,
            oracle_tool_calls=_parse_oracle_calls(oracle_tool_calls_raw),
            multimodal=_parse_multimodal(multimodal_raw),
        )

    def _load_hf(self) -> Iterator[MCPAtlasRecord]:
        from datasets import load_dataset  # type: ignore[import]
        # Revision pinned; see run_eval.DATASET_REVISION for the reasoning.
        for row in load_dataset(
            "ScaleAI/MCP-Atlas", split="train", revision="8c563b55d7c967755f474299848049834d624617"
        ):
            yield self._make_record(
                row["TASK"], row["PROMPT"], row["GTFA_CLAIMS"],
                tools_raw=row.get("ENABLED_TOOLS"),
            )

    def _load_csv(self, path: Path) -> Iterator[MCPAtlasRecord]:
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                raw_id = row.get("TASK") or row.get("task_id", "")
                prompt = row.get("PROMPT") or row.get("prompt", "")
                claims = row.get("GTFA_CLAIMS") or row.get("gtfa_claims", "")
                tools_raw = row.get("ENABLED_TOOLS") or row.get("enabled_tools") or None
                data_dir = row.get("DATA_DIR") or row.get("data_dir") or None
                tests_dir = row.get("TESTS_DIR") or row.get("tests_dir") or None
                oracle_calls = row.get("ORACLE_TOOL_CALLS") or row.get("oracle_tool_calls") or None
                multimodal = row.get("MULTIMODAL") or row.get("multimodal") or None
                if raw_id and prompt:
                    yield self._make_record(
                        raw_id, prompt, claims, tools_raw=tools_raw,
                        data_dir_raw=data_dir, tests_dir_raw=tests_dir,
                        oracle_tool_calls_raw=oracle_calls,
                        multimodal_raw=multimodal,
                    )

    def _load_parquet(self, path: Path) -> Iterator[MCPAtlasRecord]:
        import pyarrow.parquet as pq  # type: ignore[import]
        table = pq.read_table(path)
        cols = table.schema.names
        for batch in table.to_batches():
            d = batch.to_pydict()
            n = len(d[cols[0]])
            for i in range(n):
                raw_id = str(d.get("TASK", d.get("task_id", [""] * n))[i] or "")
                prompt = str(d.get("PROMPT", d.get("prompt", [""] * n))[i] or "")
                claims = d.get("GTFA_CLAIMS", d.get("gtfa_claims", [""] * n))[i]
                tools_raw = d.get("ENABLED_TOOLS", d.get("enabled_tools", [None] * n))[i]
                if raw_id and prompt:
                    yield self._make_record(raw_id, prompt, claims, tools_raw=tools_raw)

    def _load_jsonl(self, path: Path) -> Iterator[MCPAtlasRecord]:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"Warning: skipping malformed line: {e}", file=sys.stderr)
                    continue
                raw_id = row.get("TASK") or row.get("task_id", "")
                prompt = row.get("PROMPT") or row.get("prompt", "")
                claims = row.get("GTFA_CLAIMS") or row.get("gtfa_claims", [])
                tools_raw = row.get("ENABLED_TOOLS") or row.get("enabled_tools") or None
                data_dir = row.get("DATA_DIR") or row.get("data_dir") or None
                tests_dir = row.get("TESTS_DIR") or row.get("tests_dir") or None
                oracle_calls = row.get("ORACLE_TOOL_CALLS") or row.get("oracle_tool_calls") or None
                multimodal = row.get("MULTIMODAL") or row.get("multimodal") or None
                if raw_id and prompt:
                    yield self._make_record(
                        raw_id, prompt, claims, tools_raw=tools_raw,
                        data_dir_raw=data_dir, tests_dir_raw=tests_dir,
                        oracle_tool_calls_raw=oracle_calls,
                        multimodal_raw=multimodal,
                    )


class MCPAtlasToHarbor:
    def __init__(
        self,
        out_root: Path,
        *,
        image: str = DEFAULT_IMAGE,
        category: str = DEFAULT_CATEGORY,
        judge_model: str = DEFAULT_JUDGE_MODEL,
        agent_timeout: int = DEFAULT_AGENT_TIMEOUT,
        weighted: bool = False,
        org: str = DEFAULT_ORG,
        network_mode: str = DEFAULT_NETWORK_MODE,
        sandbox_port: int = DEFAULT_SANDBOX_PORT,
    ) -> None:
        self.out_root = out_root
        self.image = image
        self.category = category
        self.judge_model = judge_model
        self.agent_timeout = agent_timeout
        self.org = org
        self.network_mode = network_mode
        self.sandbox_port = sandbox_port
        # See WEIGHTED_TEST_SH's docstring: ships inert (both component
        # weights 0) until a task author opts a component in, so turning
        # this on doesn't change any existing task's score by default.
        self.weighted = weighted

    def generate_task(self, record: MCPAtlasRecord, *, overwrite: bool = False) -> Path:
        task_dir = self.out_root / record.task_id
        if task_dir.exists() and not overwrite:
            return task_dir
        for sub in ("environment", "tests", "solution"):
            (task_dir / sub).mkdir(parents=True, exist_ok=True)
        (task_dir / "instruction.md").write_text(record.prompt + "\n", encoding="utf-8")
        (task_dir / "task.toml").write_text(
            TASK_TOML_TEMPLATE.format(
                schema_version=HARBOR_SCHEMA_VERSION,
                package_name=_toml_escape(f"{self.org}/{record.task_id}"),
                description=_toml_escape(_describe(record)),
                category=_toml_escape(self.category),
                task_id=_toml_escape(record.task_id),
                image=_toml_escape(self.image),
                agent_timeout=self.agent_timeout,
                judge_model=_toml_escape(self.judge_model),
                network_mode=_toml_escape(self.network_mode),
                sandbox_port=self.sandbox_port,
                bridge_dir=BRIDGE_DIR,
                bridge_filename=BRIDGE_FILENAME,
                enabled_tools_path=ENABLED_TOOLS_PATH,
                healthcheck_command=_toml_escape(
                    HEALTHCHECK_COMMAND.format(sandbox_port=self.sandbox_port)
                ),
                artifacts=ARTIFACTS_TEMPLATE.format(task_output_path=TASK_OUTPUT_PATH),
            ),
            encoding="utf-8",
        )
        (task_dir / "environment" / "Dockerfile").write_text(
            DOCKERFILE_TEMPLATE.format(
                bridge_dir=BRIDGE_DIR,
                bridge_filename=BRIDGE_FILENAME,
                enabled_tools_path=ENABLED_TOOLS_PATH,
            ),
            encoding="utf-8",
        )
        (task_dir / "environment" / "docker-compose.yaml").write_text(
            DOCKER_COMPOSE_TEMPLATE.format(
                image=self.image,
                sandbox_port=self.sandbox_port,
                sidecar_volumes=(
                    SIDECAR_VOLUMES_TEMPLATE.format(task_data_path=TASK_DATA_PATH)
                    if record.data_dir
                    else ""
                ),
            ),
            encoding="utf-8",
        )
        if record.data_dir:
            source = Path(record.data_dir)
            if not source.is_dir():
                raise FileNotFoundError(f"data_dir does not exist: {source}")
            shutil.copytree(source, task_dir / "environment" / "task_data", dirs_exist_ok=True)
        # The per-task tool allowlist. Previously parsed off the dataset row
        # and then dropped on the floor, which silently handed every task the
        # sandbox's full 307-tool surface instead of the tools it was scoped
        # to. The bridge reads this file to filter tools/list and to refuse
        # calls to tools outside it.
        (task_dir / "environment" / "enabled_tools.txt").write_text(
            "".join(f"{t}\n" for t in record.enabled_tools),
            encoding="utf-8",
        )
        if record.multimodal:
            (task_dir / "environment" / "multimodal.json").write_text(
                json.dumps(record.multimodal, indent=2), encoding="utf-8"
            )
        # Staged into the image by the Dockerfile above; the agent runs it as
        # a stdio MCP server.
        (task_dir / "environment" / BRIDGE_FILENAME).write_text(
            _read_bridge_source(), encoding="utf-8"
        )
        test_sh = task_dir / "tests" / "test.sh"
        # A task that ships grading files needs the weighted verifier to run
        # them, regardless of the generator-wide --weighted flag.
        if self.weighted or record.tests_dir:
            test_sh.write_text(WEIGHTED_TEST_SH, encoding="utf-8")
            (task_dir / "tests" / "test_weights.json").write_text(TEST_WEIGHTS_JSON_STUB, encoding="utf-8")
            (task_dir / "tests" / "test_outputs.py").write_text(TEST_OUTPUTS_PY_STUB, encoding="utf-8")
            (task_dir / "tests" / "rubric.json").write_text(
                json.dumps(_claims_to_weighted_rubric(record.gtfa_claims), indent=2), encoding="utf-8"
            )
            (task_dir / "tests" / "traj_asserts.py").write_text(
                _read_scoring_module_source("traj_asserts.py"), encoding="utf-8"
            )
            (task_dir / "tests" / "weighted_judge.py").write_text(
                _read_scoring_module_source("weighted_judge.py"), encoding="utf-8"
            )
            # Needed by weighted_judge_entry.py to apply per-criterion weights
            # and polarity to agent_judge.py's verdicts.
            (task_dir / "tests" / "rubric_weighted.py").write_text(
                _read_scoring_module_source("rubric_weighted.py"), encoding="utf-8"
            )
            (task_dir / "tests" / "weighted_judge_entry.py").write_text(
                WEIGHTED_JUDGE_ENTRY_TEMPLATE, encoding="utf-8"
            )
        else:
            test_sh.write_text(TEST_SH, encoding="utf-8")
        test_sh.chmod(0o755)
        rubrics = _claims_to_rubrics(record.gtfa_claims)
        (task_dir / "tests" / "agent_judge.py").write_text(
            AGENT_JUDGE_TEMPLATE.format(
                criteria_json=repr(rubrics),
                agent_prompt_repr=repr(record.prompt),
            ),
            encoding="utf-8",
        )
        # Task-authored grading files land last so they win over the stubs.
        if record.tests_dir:
            source = Path(record.tests_dir)
            if not source.is_dir():
                raise FileNotFoundError(f"tests_dir does not exist: {source}")
            for item in sorted(source.iterdir()):
                if item.is_file():
                    shutil.copy2(item, task_dir / "tests" / item.name)

        solve_sh = task_dir / "solution" / "solve.sh"
        solve_sh.write_text(
            SOLVE_SH_TEMPLATE.format(
                claims_json=repr(record.gtfa_claims),
                oracle_tool_calls_json=repr(record.oracle_tool_calls),
            ),
            encoding="utf-8",
        )
        solve_sh.chmod(0o755)
        return task_dir

    def generate_many(
        self,
        records: Iterator[MCPAtlasRecord],
        *,
        overwrite: bool = False,
        ids: set[str] | None = None,
        limit: int = 0,
    ) -> list[Path]:
        results: list[Path] = []
        for record in records:
            if ids is not None and record.task_id not in ids:
                continue
            try:
                path = self.generate_task(record, overwrite=overwrite)
                results.append(path)
                n = len(results)
                if n % 100 == 0:
                    print(f"  generated {n} tasks...", file=sys.stderr)
                if limit and n >= limit:
                    break
            except Exception as e:
                print(f"Warning: skipped {record.task_id!r}: {e}", file=sys.stderr)
        return results
