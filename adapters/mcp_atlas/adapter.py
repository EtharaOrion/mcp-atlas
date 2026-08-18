from __future__ import annotations

import ast
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

_MEVAL = Path(__file__).parent.parent.parent / "services" / "mcp_eval"
sys.path.insert(0, str(_MEVAL))
from convert_tasks_to_harbor import (  # noqa: E402
    AGENT_JUDGE_TEMPLATE,
    SOLVE_SH,
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
DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"
DEFAULT_AGENT_TIMEOUT = 1800

DOCKERFILE_TEMPLATE = """\
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
"""

DOCKER_COMPOSE_TEMPLATE = """\
services:
  mcp-server:
    image: {image}
"""

# {{VAR}} → ${VAR} after .format(); Harbor expands ${VAR:-} at runtime.
TASK_TOML_TEMPLATE = """\
version = "1.0"

[metadata]
category = "{category}"
task_id = "{task_id}"
image = "{image}"

[agent]
timeout = {agent_timeout}

[environment]
cpus = 4
memory_mb = 10240
storage_mb = 10240

[environment.healthcheck]
command = "curl -sf http://mcp-server:1984/health"
interval_sec = 5
timeout_sec = 10
start_period_sec = 180
retries = 36

[verifier]
timeout_sec = 900.0

[verifier.env]
ANTHROPIC_API_KEY = "${{ANTHROPIC_API_KEY:-}}"
ANTHROPIC_BASE_URL = "${{ANTHROPIC_BASE_URL:-}}"
JUDGE_MODEL = "{judge_model}"
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


class MCPAtlasLoader:
    def __init__(
        self,
        source: str | Path | None = None,
        tool_map: dict[str, list[str]] | None = None,
    ) -> None:
        self._source = source
        self._tool_map: dict[str, list[str]] = tool_map or {}

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
    ) -> MCPAtlasRecord:
        safe_id = _sanitize_id(raw_id)
        claims = _parse_claims(claims_raw)
        if tools_raw is not None:
            tools = _parse_claims(tools_raw) if isinstance(tools_raw, str) else list(tools_raw)
        else:
            tools = self._tool_map.get(raw_id, self._tool_map.get(safe_id, []))
        return MCPAtlasRecord(task_id=safe_id, prompt=prompt, gtfa_claims=claims, enabled_tools=tools)

    def _load_hf(self) -> Iterator[MCPAtlasRecord]:
        from datasets import load_dataset  # type: ignore[import]
        for row in load_dataset("ScaleAI/MCP-Atlas", split="train"):
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
                if raw_id and prompt:
                    yield self._make_record(raw_id, prompt, claims, tools_raw=tools_raw)

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
                if raw_id and prompt:
                    yield self._make_record(raw_id, prompt, claims)


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
    ) -> None:
        self.out_root = out_root
        self.image = image
        self.category = category
        self.judge_model = judge_model
        self.agent_timeout = agent_timeout
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
                category=_toml_escape(self.category),
                task_id=_toml_escape(record.task_id),
                image=_toml_escape(self.image),
                agent_timeout=self.agent_timeout,
                judge_model=_toml_escape(self.judge_model),
            ),
            encoding="utf-8",
        )
        (task_dir / "environment" / "Dockerfile").write_text(
            DOCKERFILE_TEMPLATE,
            encoding="utf-8",
        )
        (task_dir / "environment" / "docker-compose.yaml").write_text(
            DOCKER_COMPOSE_TEMPLATE.format(image=self.image),
            encoding="utf-8",
        )
        test_sh = task_dir / "tests" / "test.sh"
        if self.weighted:
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
        solve_sh = task_dir / "solution" / "solve.sh"
        solve_sh.write_text(SOLVE_SH, encoding="utf-8")
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
