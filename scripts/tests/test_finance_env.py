"""The ODOO_*/FINANCE_* gate in scripts/run_task.sh.

finance_reporter.py is called WITHOUT --strict, so a bad enum raises inside
build_payload, prints one stderr line, and returns 0 -- the run reports success
having posted nothing (finance_reporter.py:354, 400-402). These cover the gate
that moves that failure to second zero, before the agent phase spends anything.

Every failing case exits in dispatch, before stage_preflight touches Docker, so
nothing here builds an image or reaches the network.
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
RUN_TASK = REPO / "scripts" / "run_task.sh"

# A real bundle, only so the `task.toml` existence check passes. No stage that
# reads it ever runs: the gate exits first.
TASK = "tasks/leith-herring-cure-restatement"

VALID = {
    "ODOO_URL": "https://odoo.example",
    "ODOO_AUTH_TOKEN": "t",
    "FINANCE_PROJECT_ID": "PRJ-512",
    "FINANCE_PROJECT_TYPE": "Technical",
    "FINANCE_TEAM_TYPE": "Projects",
    "FINANCE_BUDGET_TYPE": "RFP",
    "FINANCE_RFP_SUB_TYPE": "Testing",
    "FINANCE_PRODUCTION_MODE": "",
    "FINANCE_PHASE_NUMBER": "1",
}


def run(**overrides):
    e = dict(os.environ)
    e.update(VALID)
    e.update(overrides)
    return subprocess.run(
        [str(RUN_TASK), "--stage", "preflight", TASK],
        capture_output=True, text=True, env=e, cwd=str(REPO), timeout=120)


@pytest.mark.parametrize("override,needle", [
    # Case is the whole point: the reporter compares against ("Testing",
    # "Sampling") literally, so "testing" is rejected.
    ({"FINANCE_RFP_SUB_TYPE": "testing"}, "FINANCE_RFP_SUB_TYPE must be exactly"),
    ({"FINANCE_BUDGET_TYPE": "rfp"}, "FINANCE_BUDGET_TYPE must be exactly"),
    # The one key with no default anywhere: build_payload raises outright.
    ({"FINANCE_PROJECT_ID": ""}, "FINANCE_PROJECT_ID is empty or unset"),
    # env("FINANCE_PRODUCTION_MODE") is called with no fallback, so empty is a
    # hard error under Production rather than a silent default.
    ({"FINANCE_BUDGET_TYPE": "Production", "FINANCE_PRODUCTION_MODE": ""},
     "FINANCE_PRODUCTION_MODE is required"),
    ({"FINANCE_BUDGET_TYPE": "Production", "FINANCE_PRODUCTION_MODE": "single"},
     "FINANCE_PRODUCTION_MODE must be exactly"),
    ({"ODOO_URL": "projects-stage.ethara.ai"}, "ODOO_URL must start with"),
    ({"FINANCE_PHASE_NUMBER": "one"}, "FINANCE_PHASE_NUMBER must be a number"),
])
def test_bad_value_stops_the_run_before_it_starts(override, needle):
    r = run(**override)
    assert r.returncode == 4, r.stdout + r.stderr
    assert needle in r.stderr
    # Nothing downstream ran: the gate is in dispatch, above every stage.
    assert "harbor run" not in r.stdout


def test_empty_optional_values_fall_back_the_way_the_reporter_does():
    """env() is `(os.environ.get(name) or default)` -- "" and unset are the same
    thing to it, so an empty value with a default is legal, not an error."""
    r = run(FINANCE_RFP_SUB_TYPE="", FINANCE_BUDGET_TYPE="", FINANCE_PHASE_NUMBER="")
    assert "finance: OK" in r.stdout, r.stdout + r.stderr
    assert "rfp_sub_type=Testing" in r.stdout


def test_empty_odoo_url_disables_reporting_instead_of_demanding_attribution():
    r = run(ODOO_URL="", FINANCE_PROJECT_ID="")
    assert "usage reporting disabled" in r.stdout, r.stdout + r.stderr
    assert r.returncode != 4


def test_case_only_mismatch_warns_but_does_not_block():
    """project_type and team_type are forwarded to Odoo unvalidated
    (finance_reporter.py:276,279), so a casing slip can only be a warning."""
    r = run(FINANCE_PROJECT_TYPE="technical")
    assert "differs only in CASE" in r.stderr
    assert r.returncode != 4


def test_the_gate_can_be_bypassed():
    r = run(FINANCE_ENV_CHECK_OFF="1", FINANCE_PROJECT_ID="")
    assert r.returncode != 4
    assert "finance env check FAILED" not in r.stderr
