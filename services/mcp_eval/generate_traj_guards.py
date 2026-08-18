#!/usr/bin/env python3
"""
services/mcp_eval/generate_traj_guards.py

Backfill weighted-grading scaffolding onto Harbor task bundles that were
already rendered (by convert_tasks_to_harbor.py / adapters/mcp_atlas/adapter.py)
*without* --weighted, or that predate that flag entirely.

This does NOT fabricate guard rules -- it has no way to know what a "bad"
tool call looks like for an arbitrary task. What it does is scaffold: for
each enabled tool in a task's environment/enabled_tools.txt, it writes a
*commented-out* example test_* function into tests/test_outputs.py, so a
human reviewing the task only has to uncomment/adapt lines and assign a
signed weight in tests/test_weights.json, instead of writing traj_asserts
boilerplate from scratch. tests/test_weights.json itself ships fully inert
(both components weight 0) -- see WEIGHTED_TEST_SH's docstring in
convert_tasks_to_harbor.py. So running this script over a directory of
existing bundles changes zero scores until someone actually opts a test in.

Idempotent / non-destructive by default: a task whose tests/test_weights.json
already exists is skipped unless --overwrite is passed, so re-running this
over a partially-backfilled directory (or one where some tasks already used
--weighted at render time) is safe.

Usage:
    python services/mcp_eval/generate_traj_guards.py --tasks-dir output/harbor
    python services/mcp_eval/generate_traj_guards.py --tasks-dir output/harbor --dry-run
    python services/mcp_eval/generate_traj_guards.py --tasks-dir output/harbor \\
        --task-ids 689bd255c0422b257e7dfcf4,689e0b1d9c8e2ac413c1f25c --overwrite
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from convert_tasks_to_harbor import (  # noqa: E402
    TEST_WEIGHTS_JSON_STUB,
    WEIGHTED_JUDGE_ENTRY_TEMPLATE,
    WEIGHTED_TEST_SH,
    _read_scoring_module_source,
)


def _enabled_tools(task_dir: Path) -> list[str]:
    tools_file = task_dir / "environment" / "enabled_tools.txt"
    if not tools_file.exists():
        return []
    return [line.strip() for line in tools_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def _render_test_outputs_py(task_id: str, tools: list[str]) -> str:
    lines = [
        f'"""Channel A trajectory assertions for task {task_id}.',
        "",
        "Scaffolded from this task's environment/enabled_tools.txt by",
        "generate_traj_guards.py -- every example below is commented out and",
        "tests/test_weights.json ships inert, so this file changes nothing",
        "until a human uncomments/adapts an example and gives it a non-zero",
        "signed weight in test_weights.json: positive for a goal test",
        "(passing earns credit), negative for a guard test (passing means the",
        "guard's bad behavior happened -- it's a penalty, not a bonus).",
        "",
        "Every assertion should still be phrased positively (\"X happened\");",
        "the sign of the weight in test_weights.json is what makes it a goal",
        "or a guard, not the wording here.",
        '"""',
        "from traj_asserts import called_with, called_any, never_called, tool_errored  # noqa: F401",
        "",
    ]
    if not tools:
        lines.append("# No environment/enabled_tools.txt found for this task -- nothing to scaffold.")
    for tool in tools:
        fn_goal = f"test_used_{tool}"
        lines.append(f"# Example goal test -- give a POSITIVE weight in test_weights.json:")
        lines.append(f"# def {fn_goal}():")
        lines.append(f'#     assert called_with("{tool}")')
        lines.append("")
        fn_guard = f"test_no_error_from_{tool}"
        lines.append(f"# Example guard test -- give a NEGATIVE weight in test_weights.json:")
        lines.append(f"# def {fn_guard}():")
        lines.append(f'#     assert not tool_errored("{tool}")')
        lines.append("")
    return "\n".join(lines) + "\n"


def backfill_task(task_dir: Path, *, overwrite: bool = False, dry_run: bool = False) -> str:
    """Returns one of 'backfilled', 'skipped-no-tests-dir', 'skipped-exists'."""
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return "skipped-no-tests-dir"

    weights_file = tests_dir / "test_weights.json"
    if weights_file.exists() and not overwrite:
        return "skipped-exists"

    if dry_run:
        return "backfilled"

    task_id = task_dir.name
    tools = _enabled_tools(task_dir)

    weights_file.write_text(TEST_WEIGHTS_JSON_STUB, encoding="utf-8")
    (tests_dir / "test_outputs.py").write_text(_render_test_outputs_py(task_id, tools), encoding="utf-8")
    (tests_dir / "traj_asserts.py").write_text(_read_scoring_module_source("traj_asserts.py"), encoding="utf-8")
    (tests_dir / "weighted_judge.py").write_text(_read_scoring_module_source("weighted_judge.py"), encoding="utf-8")
    (tests_dir / "weighted_judge_entry.py").write_text(WEIGHTED_JUDGE_ENTRY_TEMPLATE, encoding="utf-8")

    test_sh = tests_dir / "test.sh"
    test_sh.write_text(WEIGHTED_TEST_SH, encoding="utf-8")
    test_sh.chmod(0o755)

    return "backfilled"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tasks-dir", type=Path, required=True, help="Directory of <task_id>/ Harbor bundles")
    p.add_argument("--task-ids", default=None, help="Comma-separated subset of task_ids to backfill (default: all)")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-backfill tasks that already have a tests/test_weights.json")
    p.add_argument("--dry-run", action="store_true", help="Report what would change without writing anything")
    args = p.parse_args()

    if not args.tasks_dir.is_dir():
        print(f"error: {args.tasks_dir} is not a directory", file=sys.stderr)
        return 1

    wanted = set(args.task_ids.split(",")) if args.task_ids else None
    counts = {"backfilled": 0, "skipped-no-tests-dir": 0, "skipped-exists": 0}

    for task_dir in sorted(args.tasks_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        if wanted is not None and task_dir.name not in wanted:
            continue
        status = backfill_task(task_dir, overwrite=args.overwrite, dry_run=args.dry_run)
        counts[status] = counts.get(status, 0) + 1
        if status == "backfilled":
            verb = "would backfill" if args.dry_run else "backfilled"
            print(f"  {verb}: {task_dir.name}")

    print(
        f"{counts['backfilled']} backfilled, "
        f"{counts['skipped-exists']} already opted in (use --overwrite to redo), "
        f"{counts['skipped-no-tests-dir']} not a task bundle"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
