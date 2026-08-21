"""Run pytest against a task's tests directory with weight-aware collection.

Weight resolution order (first match wins):
  1. Exact nodeid in `tests/weights.yaml`  (e.g. "test_probes.py::test_x")
  2. Function name in `tests/weights.yaml` (e.g. "test_x")
  3. `@pytest.mark.weight(N)` on the test
  4. 1.0

Outcome categories:
  - passed   — call phase succeeded
  - failed   — call phase failed (assertion or in-test exception)
  - errored  — setup/teardown failed, fixture crashed, or collection error
              (i.e. the test *couldn't run* properly)
  - skipped  — pytest.skip / xfail-skip

Errored tests contribute 0 to `pytest_weights_percentage` (same as failed) but
are tracked separately in the JSON outputs and in `tests-status.json`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.scoring.trajectory_io import load_trajectory


class _SandboxClient:
    def __init__(self, sandbox_url: str) -> None:
        self._url = sandbox_url.rstrip("/")

    def call_tool(self, name: str, args: dict) -> dict:
        """Wraps the sandbox's raw list response into {content, isError} so
        pytest fixtures and the harness client see the same result shape."""
        import urllib.error
        import urllib.request

        body = json.dumps({"tool_name": name, "tool_args": args}).encode()
        req = urllib.request.Request(
            f"{self._url}/call-tool",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                raw = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            err_text = e.read().decode(errors="replace") if e.fp else str(e)
            return {"content": [{"type": "text", "text": err_text}], "isError": True}

        if isinstance(raw, dict) and "content" in raw and "isError" in raw:
            return raw
        if isinstance(raw, list):
            return {"content": raw, "isError": False}
        return {"content": [{"type": "text", "text": str(raw)}], "isError": False}


def _load_weights_file(tests_dir: Path) -> dict[str, float]:
    for name in ("weights.yaml", "weights.yml", "weights.json"):
        p = tests_dir / name
        if p.exists():
            if p.suffix == ".json":
                raw = json.loads(p.read_text())
            else:
                raw = yaml.safe_load(p.read_text()) or {}
            if isinstance(raw, dict) and "weights" in raw:
                raw = raw["weights"]
            if not isinstance(raw, dict):
                return {}
            return {str(k): float(v) for k, v in raw.items()}
    return {}


def _resolve_weight(nodeid: str, funcname: str, marker_weight: float | None, from_file: dict[str, float]) -> float:
    if nodeid in from_file:
        return from_file[nodeid]
    if funcname in from_file:
        return from_file[funcname]
    if marker_weight is not None:
        return marker_weight
    return 1.0


class _WeightCollectorPlugin:
    def __init__(self, weights_from_file: dict[str, float]) -> None:
        self.weights_from_file = weights_from_file
        self.weights: dict[str, float] = {}
        self.outcomes: dict[str, dict[str, Any]] = {}

    def pytest_configure(self, config):
        config.addinivalue_line("markers", "weight(w): weight of this test")

    def pytest_collection_modifyitems(self, items):
        for item in items:
            marker = item.get_closest_marker("weight")
            marker_weight: float | None = None
            if marker and marker.args:
                try:
                    marker_weight = float(marker.args[0])
                except (TypeError, ValueError):
                    marker_weight = None
            funcname = item.name.split("[")[0]  # strip parametrize suffix
            weight = _resolve_weight(item.nodeid, funcname, marker_weight, self.weights_from_file)
            self.weights[item.nodeid] = weight
            self.outcomes.setdefault(
                item.nodeid,
                {"outcome": "pending", "error": None},
            )

    def pytest_collectreport(self, report):
        if report.failed:
            nodeid = report.nodeid or "<collection>"
            self.outcomes[nodeid] = {
                "outcome": "errored",
                "error": f"collection error: {report.longrepr}",
            }
            self.weights.setdefault(nodeid, 1.0)

    def pytest_runtest_logreport(self, report):
        current = self.outcomes.get(report.nodeid, {})
        # Sticky: once a bad outcome is recorded, later phases can't overwrite it.
        if current.get("outcome") in {"failed", "errored"}:
            return

        if report.when == "setup":
            if report.failed:
                self.outcomes[report.nodeid] = {"outcome": "errored", "error": f"setup failed: {report.longrepr}"}
            elif report.skipped:
                self.outcomes[report.nodeid] = {"outcome": "skipped", "error": None}
        elif report.when == "call":
            if report.passed:
                self.outcomes[report.nodeid] = {"outcome": "passed", "error": None}
            elif report.skipped:
                self.outcomes[report.nodeid] = {"outcome": "skipped", "error": None}
            else:
                # "failed" = assertion error; "errored" = unexpected exception.
                longrepr_str = str(report.longrepr)
                is_assertion = "AssertionError" in longrepr_str or "assert " in longrepr_str.lower()[:200]
                self.outcomes[report.nodeid] = {
                    "outcome": "failed" if is_assertion else "errored",
                    "error": longrepr_str,
                }
        elif report.when == "teardown" and report.failed:
            # Teardown failure after a passing call promotes the outcome to errored.
            if current.get("outcome") == "passed":
                self.outcomes[report.nodeid] = {
                    "outcome": "errored",
                    "error": f"teardown failed: {report.longrepr}",
                }


def _make_fixture_plugin(trajectory_path: Path, sandbox_url: str):
    import types

    module = types.ModuleType("_scoring_fixture_plugin")

    @pytest.fixture(scope="session")
    def trajectory():
        return load_trajectory(Path(trajectory_path))

    @pytest.fixture(scope="session")
    def sandbox():
        return _SandboxClient(sandbox_url)

    module.trajectory = trajectory
    module.sandbox = sandbox
    return module


def _infer_task_id_and_run(trajectory_path: Path) -> tuple[str | None, int | None]:
    parents = list(Path(trajectory_path).parents)
    run_dir = parents[0] if parents else None
    task_dir = parents[1] if len(parents) > 1 else None
    run_num: int | None = None
    if run_dir is not None:
        m = re.match(r"^run(\d+)$", run_dir.name)
        if m:
            run_num = int(m.group(1))
    return (task_dir.name if task_dir else None), run_num


def _tests_dir_has_tests(tests_dir: Path) -> bool:
    if not tests_dir.exists() or not tests_dir.is_dir():
        return False
    for p in tests_dir.rglob("test_*.py"):
        if p.is_file():
            return True
    return False


def score_pytest(
    tests_dir: Path,
    trajectory_path: Path,
    sandbox_url: str,
    output_path: Path,
    status_path: Path | None = None,
    log_path: Path | None = None,
) -> dict:
    """Run pytest. Writes pytest-score.json and tests-status.json.

    status_path defaults to `<output_path>.parent / tests-status.json`.
    log_path, if provided, captures pytest stdout/stderr via --log-file.
    """
    tests_dir = Path(tests_dir)
    trajectory_path = Path(trajectory_path)
    output_path = Path(output_path)
    if status_path is None:
        status_path = output_path.parent / "tests-status.json"

    task_id, run_num = _infer_task_id_and_run(trajectory_path)

    if not _tests_dir_has_tests(tests_dir):
        output = {
            "task_id": task_id,
            "run": run_num,
            "skipped": "no tests defined",
            "final_reward": None,
            "pytest_weights_percentage": None,
            "counts": {"passed": 0, "failed": 0, "errored": 0, "skipped": 0, "total": 0},
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, indent=2))
        Path(status_path).write_text(json.dumps({
            "task_id": task_id, "run": run_num,
            "counts": output["counts"], "tests": [],
            "skipped": "no tests defined",
        }, indent=2))
        return output

    weights_from_file = _load_weights_file(tests_dir)
    collector = _WeightCollectorPlugin(weights_from_file)
    fixture_plugin = _make_fixture_plugin(trajectory_path, sandbox_url)

    pytest_args = [
        str(tests_dir),
        "-p", "no:cacheprovider",
        "--tb=short",
        "-v",
        "-rA",
    ]

    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        pytest_args += ["--log-file", str(log_path), "--log-file-level", "INFO"]

    pytest.main(pytest_args, plugins=[collector, fixture_plugin])

    tests: list[dict[str, Any]] = []
    total_weight = sum(collector.weights.values())
    final_reward = 0.0
    counts = {"passed": 0, "failed": 0, "errored": 0, "skipped": 0}

    for nodeid, weight in collector.weights.items():
        info = collector.outcomes.get(nodeid, {"outcome": "errored", "error": "no report recorded"})
        outcome = info["outcome"]
        if outcome == "pending":
            outcome = "errored"
            info = {"outcome": "errored", "error": "test collected but never reported"}
        counts[outcome] = counts.get(outcome, 0) + 1
        normalized = (weight / total_weight) if total_weight > 0 else 0.0
        if outcome == "passed":
            final_reward += normalized
        tests.append({
            "nodeid": nodeid,
            "weight": weight,
            "normalized_weight": normalized,
            "outcome": outcome,
            "error": info.get("error"),
        })

    counts["total"] = sum(v for k, v in counts.items() if k != "total")

    output = {
        "task_id": task_id,
        "run": run_num,
        "weights_source": "weights.yaml" if weights_from_file else "marker_or_default",
        "counts": counts,
        "tests": tests,
        "final_reward": final_reward,
        "pytest_weights_percentage": final_reward * 100.0,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))

    status = {
        "task_id": task_id,
        "run": run_num,
        "counts": counts,
        "tests": [{"nodeid": t["nodeid"], "outcome": t["outcome"], "weight": t["weight"]} for t in tests],
    }
    Path(status_path).parent.mkdir(parents=True, exist_ok=True)
    Path(status_path).write_text(json.dumps(status, indent=2))
    return output


def _cli() -> None:
    p = argparse.ArgumentParser(description="Run task pytest suite with weight-aware scoring.")
    p.add_argument("--tests-dir", required=True, type=Path)
    p.add_argument("--trajectory", required=True, type=Path)
    p.add_argument("--sandbox-url", required=True, type=str)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--status", type=Path, default=None)
    p.add_argument("--log", type=Path, default=None)
    args = p.parse_args()

    result = score_pytest(
        tests_dir=args.tests_dir,
        trajectory_path=args.trajectory,
        sandbox_url=args.sandbox_url,
        output_path=args.output,
        status_path=args.status,
        log_path=args.log,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli()
