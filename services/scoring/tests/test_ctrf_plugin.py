"""Unit tests for ctrf_pytest_plugin.py and collect_artifacts.py.

The plugin replaced JUnit XML as CTRF's producer. The load-bearing assertion is
therefore parity: for the same suite, the plugin's ctrf.json must match what
harbor_to_output._junit_to_ctrf() built from --junitxml, or the shipped
detail.json and report.json (both built off CTRF's rows) would shift meaning.
"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_artifacts as ca  # noqa: E402
import harbor_to_output as h2o  # noqa: E402

SUITE = textwrap.dedent("""
    import pytest

    def test_world_ends_correct():
        pytest.skip("no state channel")

    def test_listing_read():
        assert True

    def test_box_price_written():
        assert True

    def test_box_state_activated():
        assert False

    def test_guard_touched_shop():
        assert False

    def test_guard_wrote_email():
        assert True

    def test_unweighted_extra():
        assert True
""")

WEIGHTS = {
    "components": {
        "traj_tests": {
            "tests": {
                "test_world_ends_correct": 5,
                "test_listing_read": 1,
                "test_box_price_written": 5,
                "test_box_state_activated": 3,
                "test_guard_touched_shop": -3,
                "test_guard_wrote_email": -3,
            }
        }
    }
}


def _run_suite(tmp_path: Path, suite: str = SUITE, weights: dict | None = WEIGHTS):
    """Run *suite* with both the plugin and --junitxml; return (plugin, legacy)."""
    (tmp_path / "test_sample.py").write_text(suite)
    weights_path = tmp_path / "test_weights.json"
    weights_path.write_text(json.dumps(weights if weights is not None else {}))
    ctrf_path = tmp_path / "ctrf.json"
    junit_path = tmp_path / "junit.xml"

    subprocess.run(
        [sys.executable, "-m", "pytest", "test_sample.py",
         "-p", "ctrf_pytest_plugin", f"--junitxml={junit_path}", "-q"],
        cwd=tmp_path, check=False, capture_output=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
             "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
             "CTRF_OUT": str(ctrf_path), "CTRF_WEIGHTS": str(weights_path)},
    )

    plugin = json.loads(ctrf_path.read_text())
    tw_comp = ((weights or {}).get("components") or {}).get("traj_tests")
    legacy = h2o._junit_to_ctrf(junit_path, tw_comp)
    return plugin, legacy


def _blank_durations(doc: dict) -> dict:
    doc = json.loads(json.dumps(doc))
    for test in doc["results"]["tests"]:
        test["duration"] = 0
    return doc


def test_plugin_matches_junit_derived_ctrf(tmp_path):
    plugin, legacy = _run_suite(tmp_path)
    assert _blank_durations(plugin) == _blank_durations(legacy)


def test_plugin_emits_bare_names_and_weights(tmp_path):
    plugin, _ = _run_suite(tmp_path)
    tests = {t["name"]: t for t in plugin["results"]["tests"]}
    # Bare function names, not nodeids -- this is the join key against
    # test_weights.json used by harbor_to_output._build_detail().
    assert "test_box_price_written" in tests
    assert tests["test_box_price_written"]["weight"] == 5
    assert tests["test_guard_touched_shop"]["weight"] == -3
    # A test absent from test_weights.json carries no weight key at all.
    assert "weight" not in tests["test_unweighted_extra"]


def test_plugin_statuses_and_summary(tmp_path):
    plugin, _ = _run_suite(tmp_path)
    statuses = {t["name"]: t["status"] for t in plugin["results"]["tests"]}
    assert statuses["test_world_ends_correct"] == "skipped"
    assert statuses["test_box_state_activated"] == "failed"
    assert statuses["test_listing_read"] == "passed"
    summary = plugin["results"]["summary"]
    assert (summary["tests"], summary["passed"], summary["failed"], summary["skipped"]) == (7, 4, 2, 1)


def test_overall_score_ignores_negative_weights(tmp_path):
    """Guards carry negative weights: a guard must not enter the denominator.

    Positives here are listing_read (1, passed) + box_price_written (5, passed)
    + box_state_activated (3, failed); world_ends_correct (5) skipped, so it is
    excluded entirely. Score is 6/9, untouched by either guard.
    """
    plugin, _ = _run_suite(tmp_path)
    assert plugin["results"]["summary"]["overall_score"] == round(6 / 9, 6)
    assert plugin["results"]["summary"]["weighted_percentage"] == 66.67


def test_missing_weights_file_still_emits_ctrf(tmp_path):
    """A reporting artifact must survive a task that ships no weights."""
    plugin, _ = _run_suite(tmp_path, weights=None)
    assert plugin["results"]["summary"]["tests"] == 7
    assert plugin["results"]["summary"]["overall_score"] == 0.0
    assert all("weight" not in t for t in plugin["results"]["tests"])


# --- collect_artifacts -----------------------------------------------------

def test_collect_copies_agent_files_and_skips_excluded(tmp_path):
    src, dest = tmp_path / "workspace", tmp_path / "publish"
    (src / "renders").mkdir(parents=True)
    (src / "report.md").write_text("produced by the agent")
    (src / "renders" / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # The task's own input assets: read-only mount, not agent output.
    (src / "data").mkdir()
    (src / "data" / "invoice.pdf").write_bytes(b"%PDF-1.4")

    copied, total, skipped = ca.collect(src, dest, {"data"}, 10_000, 100_000)

    assert copied == 2
    assert total == len("produced by the agent") + 8
    assert not skipped
    assert (dest / "report.md").read_text() == "produced by the agent"
    assert (dest / "renders" / "chart.png").exists()
    assert not (dest / "data").exists()


def test_collect_enforces_caps_and_reports_skips(tmp_path):
    src, dest = tmp_path / "workspace", tmp_path / "publish"
    src.mkdir()
    (src / "small.txt").write_text("ok")
    (src / "huge.bin").write_bytes(b"x" * 500)

    copied, _, skipped = ca.collect(src, dest, set(), 100, 100_000)

    assert copied == 1
    assert not (dest / "huge.bin").exists()
    assert any("huge.bin" in s and "per-file cap" in s for s in skipped)


def test_collect_missing_source_is_not_fatal(tmp_path):
    copied, total, skipped = ca.collect(tmp_path / "nope", tmp_path / "out", set(), 100, 100)
    assert (copied, total) == (0, 0)
    assert skipped and "does not exist" in skipped[0]
