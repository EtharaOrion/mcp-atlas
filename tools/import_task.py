#!/usr/bin/env python3
"""Import a Terminal-Bench-style task (instruction.md + rubrics.jsonl + data/)
into the mcp-atlas tasks/<id>/ format (task.yaml + rubric.yaml + tests/).

Usage:
  python3 tools/import_task.py --input task-input/h1 --output tasks/h1
  python3 tools/import_task.py --input task-input/h1 --output tasks/h1 --k 3

Rubric mapping:
  - response_criteria / response_not_criteria  -> rubric.yaml entries
    (points sign preserved; negative points are subtracted, capped at 0)
  - probe_file_exists / probe_file_contains / shell_succeeds_real -> pytest tests
    (each test uses the `sandbox` fixture to call MCP tools on the running sandbox)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from textwrap import dedent

import yaml


DEFAULT_TOOLS = [
    "filesystem_read_text_file",
    "filesystem_write_file",
    "filesystem_list_directory",
    "mcp-code-executor_execute_code",
    "desktop-commander_execute_command",
]


def load_rubrics(path: Path) -> list[dict]:
    rubrics: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rubrics.append(json.loads(line))
    return rubrics


def split_rubrics(rubrics: list[dict]) -> tuple[list[dict], list[dict]]:
    judge_types = {"response_criteria", "response_not_criteria"}
    probe_types = {"probe_file_exists", "probe_file_contains", "shell_succeeds_real"}
    judge, probe = [], []
    for r in rubrics:
        if r["type"] in judge_types:
            judge.append(r)
        elif r["type"] in probe_types:
            probe.append(r)
        else:
            print(f"WARN: unknown rubric type {r['type']!r} in #{r.get('number')}, skipping", file=sys.stderr)
    return judge, probe


def build_rubric_yaml(judge_rubrics: list[dict]) -> dict:
    out = []
    for r in judge_rubrics:
        rid = f"r{r['number']}"
        weight = abs(r.get("points", 1))
        criterion = r["criterion"]
        if r["type"] == "response_not_criteria":
            criterion = f"[NEGATIVE — score 1.0 if the following is FALSE, 0.0 if TRUE] {criterion}"
        out.append({"id": rid, "description": criterion, "weight": weight})
    return {"rubric": out}


def build_test_file(probe_rubrics: list[dict]) -> str:
    lines = [
        "# Auto-generated from rubrics.jsonl by tools/import_task.py",
        "# Each test hits the running sandbox via the `sandbox` fixture.",
        "import json",
        "import pytest",
        "",
    ]
    for r in probe_rubrics:
        num = r["number"]
        weight = abs(r.get("points", 1))
        crit = r["criterion"].replace('"', '\\"')

        if r["type"] == "probe_file_exists":
            paths = r.get("paths", [r.get("path")])
            paths = [p for p in paths if p]
            lines.append(f"@pytest.mark.weight({weight})")
            lines.append(f"def test_r{num}_files_exist(sandbox):")
            lines.append(f'    """{crit}"""')
            lines.append(f"    for p in {paths!r}:")
            lines.append('        res = sandbox.call_tool("filesystem_read_text_file", {"path": p})')
            lines.append('        text = "".join(c.get("text","") for c in (res.get("content") or []) if isinstance(c, dict))')
            lines.append('        assert text and not res.get("isError"), f"missing/empty: {p}"')
            lines.append("")

        elif r["type"] == "probe_file_contains":
            path = r.get("path") or (r.get("paths") or [None])[0]
            pattern = r.get("pattern", "")
            ignore = bool(r.get("ignore_case", False))
            lines.append(f"@pytest.mark.weight({weight})")
            lines.append(f"def test_r{num}_file_contains(sandbox):")
            lines.append(f'    """{crit}"""')
            lines.append(f'    res = sandbox.call_tool("filesystem_read_text_file", {{"path": {path!r}}})')
            lines.append('    text = "".join(c.get("text","") for c in (res.get("content") or []) if isinstance(c, dict))')
            lines.append("    import re")
            lines.append(f"    flags = re.IGNORECASE if {ignore} else 0")
            lines.append(f"    assert re.search({pattern!r}, text, flags), f\"pattern not found in {path!r}\"")
            lines.append("")

        elif r["type"] == "shell_succeeds_real":
            shell = r.get("raw_shell", "")
            shell_json = json.dumps(shell)
            lines.append(f"@pytest.mark.weight({weight})")
            lines.append(f"def test_r{num}_shell_succeeds(sandbox):")
            lines.append(f'    """{crit}"""')
            lines.append(f"    res = sandbox.call_tool(\"desktop-commander_execute_command\", {{\"command\": {shell_json}, \"timeout_ms\": 30000}})")
            lines.append("    if res.get('isError'):")
            lines.append('        text = "".join(c.get("text","") for c in (res.get("content") or []) if isinstance(c, dict))')
            lines.append('        pytest.fail(f"shell failed: {text[:500]}")')
            lines.append("")

    return "\n".join(lines) + "\n"


def build_task_yaml(task_id: str, prompt: str, runs: int, has_data: bool, multimodal: list[dict]) -> dict:
    body: dict = {
        "task_id": task_id,
        "prompt": prompt.strip(),
        "enabled_tools": DEFAULT_TOOLS,
        "image": "ghcr.io/scaleapi/mcp-atlas:1.2.7",
        "runs": runs,
        "timeout": 1800,
        "max_turns": 128,
        "max_tool_calls": 64,
        "combine_weights": {"rubric": 0.5, "pytest": 0.5},
    }
    if multimodal:
        body["multimodal"] = multimodal
    return body


def detect_multimodal(data_dir: Path) -> list[dict]:
    """Best-effort multimodal detection. Skips unsupported formats (video, etc.)
    with a warning — the harness's multimodal schema only handles image/audio."""
    if not data_dir.is_dir():
        return []
    supported_img = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    supported_aud = {".mp3", ".wav", ".m4a"}
    mm: list[dict] = []
    for f in sorted(data_dir.iterdir()):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        rel = f"data/{f.name}"
        if ext in supported_img:
            mm.append({"type": "image", "path": rel})
        elif ext in supported_aud:
            mm.append({"type": "audio", "path": rel})
        else:
            print(f"NOTE: {f.name} has unsupported extension {ext!r} — copied to sandbox but not attached as multimodal. "
                  f"The agent will need a tool (e.g. mcp-code-executor) to open it from /data/", file=sys.stderr)
    return mm


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Source dir with instruction.md + rubrics.jsonl + data/")
    ap.add_argument("--output", required=True, help="Destination tasks/<id>/ dir")
    ap.add_argument("--k", type=int, default=1, help="runs field in task.yaml (default: 1)")
    args = ap.parse_args()

    src = Path(args.input).resolve()
    dst = Path(args.output).resolve()
    task_id = dst.name

    for req in ["instruction.md", "rubrics.jsonl"]:
        if not (src / req).exists():
            sys.exit(f"missing {src / req}")

    dst.mkdir(parents=True, exist_ok=True)
    (dst / "tests").mkdir(exist_ok=True)

    prompt = (src / "instruction.md").read_text()
    rubrics = load_rubrics(src / "rubrics.jsonl")
    judge_rubrics, probe_rubrics = split_rubrics(rubrics)

    data_src = src / "data"
    data_dst = dst / "data"
    if data_src.is_dir():
        if data_dst.exists():
            shutil.rmtree(data_dst)
        shutil.copytree(data_src, data_dst)
        note = ("\n\nAll data assets are available in the sandbox under "
                "/task_data/ (read-only). Write outputs into /tmp/ which is writable.")
        prompt = prompt + note

    multimodal = detect_multimodal(data_dst)

    task_yaml = build_task_yaml(task_id, prompt, args.k, data_dst.is_dir(), multimodal)
    (dst / "task.yaml").write_text(yaml.safe_dump(task_yaml, sort_keys=False))

    rubric_yaml = build_rubric_yaml(judge_rubrics)
    (dst / "rubric.yaml").write_text(yaml.safe_dump(rubric_yaml, sort_keys=False))

    tests_file = dst / "tests" / "test_probes.py"
    tests_file.write_text(build_test_file(probe_rubrics))

    print(f"Wrote:")
    print(f"  {dst / 'task.yaml'}")
    print(f"  {dst / 'rubric.yaml'}  ({len(judge_rubrics)} judge criteria)")
    print(f"  {tests_file}  ({len(probe_rubrics)} probe tests)")
    if data_dst.is_dir():
        print(f"  {data_dst}/  (copied assets)")
    if multimodal:
        print(f"  multimodal attached: {[m['path'] for m in multimodal]}")


if __name__ == "__main__":
    main()
