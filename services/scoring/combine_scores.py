from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import mean
from typing import Any


def _mean_or_none(vals: list[float]) -> float | None:
    return mean(vals) if vals else None


def _read_json_if_exists(path: Path) -> dict | None:
    if path.exists():
        return json.loads(path.read_text())
    return None


def write_run_score(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    rubric = _read_json_if_exists(run_dir / "rubric-score.json")
    pytest_ = _read_json_if_exists(run_dir / "pytest-score.json")

    rubric_pct = rubric.get("rubric_weights_percentage") if rubric else None
    pytest_pct = pytest_.get("pytest_weights_percentage") if pytest_ else None

    present = [v for v in (rubric_pct, pytest_pct) if v is not None]
    combined = mean(present) if present else None

    task_id = None
    run_num = None
    for src in (rubric, pytest_):
        if src:
            if task_id is None:
                task_id = src.get("task_id")
            if run_num is None:
                run_num = src.get("run")
    if task_id is None:
        task_id = run_dir.parent.name if run_dir.parent else None
    if run_num is None:
        m = re.match(r"^run(\d+)$", run_dir.name)
        if m:
            run_num = int(m.group(1))

    output = {
        "task_id": task_id,
        "run": run_num,
        "rubric_weights_percentage": rubric_pct,
        "pytest_weights_percentage": pytest_pct,
        "combined_percentage": combined,
    }
    (run_dir / "score.json").write_text(json.dumps(output, indent=2))
    return output


def _iter_run_dirs(task_dir: Path, k: int):
    for i in range(1, k + 1):
        run_dir = task_dir / f"run{i}"
        if run_dir.is_dir():
            yield i, run_dir


def write_pass_at_k_summary(task_dir: Path, k: int, threshold: float = 50.0) -> dict:
    task_dir = Path(task_dir)
    runs: list[dict[str, Any]] = []
    for run_num, run_dir in _iter_run_dirs(task_dir, k):
        score_path = run_dir / "score.json"
        score = _read_json_if_exists(score_path)
        if score is None:
            continue
        runs.append({
            "run": score.get("run", run_num),
            "rubric_weights_percentage": score.get("rubric_weights_percentage"),
            "pytest_weights_percentage": score.get("pytest_weights_percentage"),
            "combined_percentage": score.get("combined_percentage"),
        })

    rubric_vals = [r["rubric_weights_percentage"] for r in runs if r["rubric_weights_percentage"] is not None]
    pytest_vals = [r["pytest_weights_percentage"] for r in runs if r["pytest_weights_percentage"] is not None]
    combined_vals = [r["combined_percentage"] for r in runs if r["combined_percentage"] is not None]

    runs_excluded = sum(1 for r in runs if r["combined_percentage"] is None)
    passed = sum(1 for v in combined_vals if v >= threshold)
    mean_pass_rate = (passed / len(runs)) if runs else None

    summary = {
        "task_id": task_dir.name,
        "k": k,
        "runs": runs,
        "average_rubric_weights_percentage": _mean_or_none(rubric_vals),
        "average_pytest_weights_percentage": _mean_or_none(pytest_vals),
        "average_combined_percentage": _mean_or_none(combined_vals),
        "runs_excluded_from_avg": runs_excluded,
        "mean_pass_rate": mean_pass_rate,
        "threshold": threshold,
    }
    (task_dir / f"pass@{k}summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def write_model_summary(model_output_dir: Path) -> dict:
    model_output_dir = Path(model_output_dir)
    tasks: list[dict[str, Any]] = []
    k_seen: set[int] = set()

    for summary_path in sorted(model_output_dir.glob("*/pass@*summary.json")):
        data = json.loads(summary_path.read_text())
        tasks.append({
            "task_id": data.get("task_id", summary_path.parent.name),
            "average_rubric_weights_percentage": data.get("average_rubric_weights_percentage"),
            "average_pytest_weights_percentage": data.get("average_pytest_weights_percentage"),
            "average_combined_percentage": data.get("average_combined_percentage"),
            "mean_pass_rate": data.get("mean_pass_rate"),
        })
        if data.get("k") is not None:
            k_seen.add(data["k"])

    rubric_vals = [t["average_rubric_weights_percentage"] for t in tasks if t["average_rubric_weights_percentage"] is not None]
    pytest_vals = [t["average_pytest_weights_percentage"] for t in tasks if t["average_pytest_weights_percentage"] is not None]
    combined_vals = [t["average_combined_percentage"] for t in tasks if t["average_combined_percentage"] is not None]
    pass_rate_vals = [t["mean_pass_rate"] for t in tasks if t["mean_pass_rate"] is not None]

    k_val: int | None
    if len(k_seen) == 1:
        k_val = next(iter(k_seen))
    elif not k_seen:
        k_val = None
    else:
        k_val = max(k_seen)

    summary = {
        "model": model_output_dir.name,
        "k": k_val,
        "tasks": tasks,
        "average_rubric_weights_percentage": _mean_or_none(rubric_vals),
        "average_pytest_weights_percentage": _mean_or_none(pytest_vals),
        "average_combined_percentage": _mean_or_none(combined_vals),
        "average_mean_pass_rate": _mean_or_none(pass_rate_vals),
    }
    (model_output_dir / "model_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def _cli() -> None:
    p = argparse.ArgumentParser(description="Combine and roll up scoring outputs.")
    p.add_argument("mode", choices=["run", "summary", "model"])
    p.add_argument("--path", required=True, type=Path)
    p.add_argument("--k", type=int, default=1)
    p.add_argument("--threshold", type=float, default=50.0)
    args = p.parse_args()

    if args.mode == "run":
        result = write_run_score(args.path)
    elif args.mode == "summary":
        result = write_pass_at_k_summary(args.path, args.k, args.threshold)
    else:
        result = write_model_summary(args.path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli()
