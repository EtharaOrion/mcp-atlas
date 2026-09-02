from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

# Host-local path masking, inline. Harbor stamps absolute host paths
# (trial_uri, trials_dir, jobs_dir, tracebacks) into bookkeeping files, which
# is how `/Users/<name>/...` strings end up in shipped bundles. A path holding
# a repo anchor is cut to anchor-relative form (`/Users/x/dev/harness/output/t`
# -> `output/t`, still a usable pointer inside the bundle); any other
# home-rooted path gets its `/Users/<name>` or `/home/<name>` head replaced
# with `~`. Container paths (/workspace, /logs, /tmp) survive verbatim.
_ANCHORED_RE = re.compile(
    r"(?:file://)?(?:/(?:Users|home)|~)/[^\s\"'\\]*?/"
    r"(?=(?:delivery_output|output|input|tasks|jobs)(?:/|[\"'\s]|$))"
)
_HOME_RE = re.compile(r"(?:file://)?/(?:Users|home)/[^/\s\"'\\]+")

_TEXT_SUFFIXES = {".json", ".txt", ".md", ".xml", ".yaml", ".yml", ".log",
                  ".toml", ".py", ".csv", ".html", ".cfg", ".ini"}


def mask_local_paths(text: str) -> str:
    return _HOME_RE.sub("~", _ANCHORED_RE.sub("", text))


def mask_tree(root: Path) -> list[Path]:
    """Mask every text file under `root`; return the files that changed."""
    changed: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not (p.is_file() and p.suffix.lower() in _TEXT_SUFFIXES):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        masked = mask_local_paths(text)
        if masked != text:
            p.write_text(masked, encoding="utf-8")
            changed.append(p)
    return changed


def _load(path: Path, default=None):
    try:
        return json.loads(path.read_bytes())
    except Exception:
        return default


def _dump(path: Path, data) -> None:
    path.write_text(mask_local_paths(json.dumps(data, indent=2, ensure_ascii=False)) + "\n")


def _copy_masked(src: Path, dst: Path) -> None:
    """Copy a text file, masking host-local paths (Harbor's trial_uri,
    trials_dir, jobs_dir carry absolute host paths that must not ship)."""
    dst.write_text(mask_local_paths(src.read_text(encoding="utf-8", errors="replace")),
                   encoding="utf-8")


def _short_model(name: str) -> str:
    short = name.removeprefix("claude-")
    return re.sub(r"-(\d+)$", r".\1", short)


def _run_label(dir_name: str) -> str:
    return dir_name.replace("_", " ", 1)


def _rubric_cleared(item: dict) -> bool:
    positive = item.get("is_positive", True)
    passed = bool(item.get("passed"))
    return passed if positive else not passed


def _build_judge_usage(tokens: dict) -> dict:
    return {
        "input_tokens": tokens.get("judge_input_tokens", 0),
        "cache_read_input_tokens": tokens.get("judge_input_cache_tokens", 0),
        # `judge_cache_write_tokens` is the current name; `judge_output_cache_tokens`
        # is the old one and is still read so artifacts written before the rename
        # keep costing correctly. Both hold cache CREATION, which is input-side.
        "cache_creation_input_tokens": tokens.get(
            "judge_cache_write_tokens",
            tokens.get("judge_output_cache_tokens", 0)),
        "output_tokens": tokens.get("judge_output_tokens", 0),
        "cost_usd": tokens.get("judge_cost_usd", 0),
    }


def make_delivery(
    task_slug: str,
    output_dir: Path,
    tasks_dir: Path,
    delivery_dir: Path,
) -> None:
    src = output_dir / task_slug
    if not src.exists():
        sys.exit(f"Error: output dir not found: {src}")

    dst = delivery_dir / task_slug
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    task_src = tasks_dir / task_slug
    if task_src.exists():
        shutil.copytree(
            task_src,
            dst / "data",
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "*.pyo"),
        )
    else:
        print(f"Warning: task dir not found: {task_src}", file=sys.stderr)
        (dst / "data").mkdir()

    traj_src = src / "trajectory"
    traj_dst = dst / "trajectory"
    traj_dst.mkdir()

    pass_sum = _load(src / "pass_summary.json", {})
    per_run_clean = [
        {k: v for k, v in run.items() if k != "include_multimodal"}
        for run in (pass_sum.get("per_run") or [])
    ]
    delivery_pass = {k: v for k, v in pass_sum.items() if k != "per_run"}
    delivery_pass["per_run"] = per_run_clean
    _dump(traj_dst / "pass_summary.json", delivery_pass)

    # pass@N.json (pass@k rollup, N = run count) ships under its dynamic name
    # so the delivery filename itself says how many runs it covers.
    for passk_src in sorted(src.glob("pass@*.json")):
        _copy_masked(passk_src, traj_dst / passk_src.name)

    model_name: str = pass_sum.get("model", "")
    model_dst = traj_dst / _short_model(model_name)

    for run_dir in sorted(traj_src.glob("Run_*")):
        dst_run = model_dst / _run_label(run_dir.name)
        dst_run.mkdir(parents=True)

        (dst_run / "agent").mkdir()
        src_traj = run_dir / "agent" / "trajectory.json"
        if src_traj.exists():
            shutil.copy2(src_traj, dst_run / "agent" / "trajectory.json")

        arts_src = run_dir / "artifacts"
        if arts_src.exists():
            shutil.copytree(arts_src, dst_run / "artifacts")
        else:
            (dst_run / "artifacts").mkdir()

        if (run_dir / "config.json").exists():
            _copy_masked(run_dir / "config.json", dst_run / "config.json")

        report = _load(run_dir / "report.json", {})
        judge_tokens = _load(run_dir / "verifier" / "judge_tokens.json", {})
        # rubric_judge_cli writes judge_tokens.json as a LIST of per-call
        # entries (one per codex exec); older judges wrote one dict. Merge a
        # list into the dict shape _build_judge_usage expects: token counts
        # and cost sum across calls, model comes from the first entry.
        if isinstance(judge_tokens, list):
            calls = [t for t in judge_tokens if isinstance(t, dict)]
            merged = {"model_name": calls[0].get("model_name", "") if calls else ""}
            for key in ("judge_input_tokens", "judge_output_tokens",
                        "judge_input_cache_tokens", "judge_output_cache_tokens",
                        "judge_cache_write_tokens", "judge_cost_usd"):
                vals = [t[key] for t in calls if isinstance(t.get(key), (int, float))]
                if vals:
                    merged[key] = sum(vals)
            judge_tokens = merged
        report.pop("include_multimodal", None)
        report["judge_model"] = judge_tokens.get("model_name", "")
        report["judge_usage"] = _build_judge_usage(judge_tokens)
        _dump(dst_run / "report.json", report)

        if (run_dir / "result.json").exists():
            _copy_masked(run_dir / "result.json", dst_run / "result.json")

        ver_src = run_dir / "verifier"
        ver_dst = dst_run / "verifier"
        ver_dst.mkdir()

        for fname in ("ctrf.json", "test-stdout.txt"):
            if (ver_src / fname).exists():
                shutil.copy2(ver_src / fname, ver_dst / fname)

        reward_val = (_load(ver_src / "reward.json", {}) or {}).get("reward", 0)
        _dump(ver_dst / "reward.json", {"reward": reward_val})

        rubric = report.get("rubric", [])
        score_data = {
            "model": report.get("model", model_name),
            "run_index": report.get("run_index", 1),
            "rubric_weights_percentage": report.get("rubric_weights_percentage", 0),
            "total": len(rubric),
            "passed": sum(1 for r in rubric if _rubric_cleared(r)),
            "failed": sum(1 for r in rubric if not _rubric_cleared(r)),
            "reward": round(report.get("rubric_weights_percentage", 0) / 100, 4),
            "rubric": rubric,
            "judge_model": judge_tokens.get("model_name", ""),
            "judge_usage": report.get("judge_usage", {}),
        }
        _dump(ver_dst / "score.json", score_data)

    # Safety net: whatever else landed in the bundle (artifacts, logs, task
    # data), no host-local path may ship. This also catches future additions
    # to the bundle without anyone having to remember the masking rule.
    swept = mask_tree(dst)
    for p in swept:
        print(f"masked local paths in: {p.relative_to(dst)}")

    print(f"Done: {dst}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reformat output/<task>/ into delivery_output/<task>/"
    )
    parser.add_argument("task_slug", help="Task slug, e.g. bull-street-lot-expense-claim")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--tasks-dir", default="tasks")
    parser.add_argument("--delivery-dir", default="delivery_output")
    args = parser.parse_args()

    base = Path(__file__).resolve().parent.parent
    make_delivery(
        task_slug=args.task_slug,
        output_dir=base / args.output_dir,
        tasks_dir=base / args.tasks_dir,
        delivery_dir=base / args.delivery_dir,
    )


if __name__ == "__main__":
    main()
