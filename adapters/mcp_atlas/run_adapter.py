from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adapter import (
    MCPAtlasLoader,
    MCPAtlasToHarbor,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_IMAGE,
    DEFAULT_JUDGE_MODEL,
    DEFAULT_NETWORK_MODE,
    DEFAULT_ORG,
    DEFAULT_SANDBOX_PORT,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_adapter",
        description="Generate Harbor task bundles from the MCP-Atlas benchmark.",
    )
    p.add_argument("--output-dir", required=True, type=Path, metavar="DIR")
    p.add_argument("--input", type=Path, default=None, metavar="FILE",
                   help="Local .csv or .jsonl file; defaults to HuggingFace ScaleAI/MCP-Atlas.")
    p.add_argument("--limit", type=int, default=0, metavar="N",
                   help="Stop after N tasks (0 = all).")
    p.add_argument("--task-ids", nargs="+", default=None, metavar="ID",
                   help="Only generate tasks with these (sanitized) task_ids.")
    p.add_argument("--tool-map", type=Path, default=None, metavar="FILE",
                   help="JSON file mapping raw task_id → [tool, ...] from extract_mcp_servers_per_task.py.")
    p.add_argument("--overwrite", action="store_true",
                   help="Regenerate task dirs that already exist.")
    p.add_argument("--image", default=DEFAULT_IMAGE)
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p.add_argument("--agent-timeout", type=int, default=DEFAULT_AGENT_TIMEOUT)
    p.add_argument("--org", default=DEFAULT_ORG, metavar="NAME",
                   help="Package org for [task].name (org/task_id). Harbor's registry "
                        "requires it; also what `harbor task update --org` would set.")
    p.add_argument("--network-mode", default=DEFAULT_NETWORK_MODE, metavar="MODE",
                   help="Harbor [environment].network_mode. MCP-Atlas tasks reach live "
                        "third-party APIs, so this defaults to 'public'.")
    p.add_argument("--sandbox-port", type=int, default=DEFAULT_SANDBOX_PORT, metavar="PORT",
                   help="Port the mcp-atlas sidecar serves its REST API on.")
    p.add_argument("--weighted", action="store_true",
                   help="Also scaffold weighted-grading files (tests/test_weights.json, "
                        "test_outputs.py, rubric.json, weighted_judge*.py). Inert by default "
                        "-- see MCPAtlasToHarbor's docstring.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    tool_map: dict[str, list[str]] = {}
    if args.tool_map:
        tool_map = json.loads(args.tool_map.read_text(encoding="utf-8"))

    loader = MCPAtlasLoader(source=args.input, tool_map=tool_map)
    generator = MCPAtlasToHarbor(
        out_root=args.output_dir,
        image=args.image,
        judge_model=args.judge_model,
        agent_timeout=args.agent_timeout,
        weighted=args.weighted,
        org=args.org,
        network_mode=args.network_mode,
        sandbox_port=args.sandbox_port,
    )

    ids = set(args.task_ids) if args.task_ids else None
    paths = generator.generate_many(
        iter(loader),
        overwrite=args.overwrite,
        ids=ids,
        limit=args.limit,
    )
    print(f"Generated {len(paths)} task(s) → {args.output_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
