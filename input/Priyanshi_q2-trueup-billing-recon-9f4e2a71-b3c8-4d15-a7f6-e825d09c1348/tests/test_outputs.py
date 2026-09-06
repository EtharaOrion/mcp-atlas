"""
Trajectory tests for Veltrix Q2 FY2026 Enterprise True-Up Billing Reconciliation.

All tests operate exclusively on the agent trajectory (MCP tool calls made and their inputs).
No file content reading, no output file inspection, no reward infrastructure.

Positive tests return True when the agent took the expected action.
Guard tests (negative weight in test_weights.json) return True when the agent made an error —
returning True from a guard triggers a score penalty.
"""
import json
import os

TESTS_DIR = os.path.dirname(__file__)
ROOT = os.path.join(TESTS_DIR, "..")

LINEAR_WRITE_PREFIXES      = ("create_", "post_", "add_", "new_")
STRIPE_WRITE_PREFIXES      = ("create_", "update_", "delete_", "capture_", "refund_")
SALESFORCE_WRITE_PREFIXES  = ("create_", "update_", "delete_", "upsert_", "patch_")
SERVICENOW_WRITE_PREFIXES  = ("create_", "update_", "delete_", "resolve_", "close_")
QUICKBOOKS_WRITE_PREFIXES  = ("create_", "update_", "delete_", "void_", "post_")
XERO_WRITE_PREFIXES        = ("create_", "update_", "delete_", "post_", "approve_")


# ---------------------------------------------------------------------------
# Trajectory helpers
# ---------------------------------------------------------------------------

def _traj():
    """Load trajectory JSON; return list of step dicts."""
    candidates = [
        os.environ.get("TRAJ_FILE", ""),
        os.path.join(ROOT, "trajectory.json"),
        os.path.join(ROOT, "traj.json"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            return data.get("steps", data.get("trajectory", []))
    return []


def _steps():
    return _traj()


def _app(step):
    """Return the MCP server name for a step, normalised to lowercase."""
    tool = step.get("tool", step.get("tool_name", step.get("function", "")))
    if "mcp__" in tool:
        parts = tool.split("__")
        if len(parts) >= 2:
            return parts[1].lower()
    return step.get("app", step.get("mcp_server", step.get("server", ""))).lower()


def _base(step):
    """Return the base tool name (the action, without server prefix)."""
    tool = step.get("tool", step.get("tool_name", step.get("function", "")))
    if "mcp__" in tool:
        parts = tool.split("__")
        if len(parts) >= 3:
            return parts[2].lower()
    return step.get("base", step.get("action", "")).lower()


def _app_used(app_name):
    """Return True if the agent called any tool on the given MCP server."""
    target = app_name.lower()
    return any(target in _app(s) for s in _steps())


def _wrote_app(app_name, write_prefixes):
    """Return True if the agent called a write-type tool on the given MCP server."""
    target = app_name.lower()
    for step in _steps():
        if target in _app(step):
            if any(_base(step).startswith(p) for p in write_prefixes):
                return True
    return False


# ---------------------------------------------------------------------------
# Positive tests — tool call presence
# ---------------------------------------------------------------------------

def test_queried_stripe():
    """Agent must have called LightStripe to retrieve actual Q2 usage charges."""
    return _app_used("LightStripe")


def test_queried_salesforce():
    """Agent must have called LightSalesforce to obtain authoritative contract terms."""
    return _app_used("LightSalesforce")


def test_queried_servicenow():
    """Agent must have called LightServiceNow to look up the SLA incident."""
    return _app_used("LightServiceNow")


def test_queried_slack():
    """Agent must have called LightSlack to read the policy confirmation and account status messages."""
    return _app_used("LightSlack")


def test_queried_gmail():
    """Agent must have called LightGmail, where the cap waiver claim from the sales director is located."""
    return _app_used("LightGmail")


# ---------------------------------------------------------------------------
# Positive tests — LightLinear write call presence
# ---------------------------------------------------------------------------

def test_wrote_linear():
    """Agent must have made at least one write call to LightLinear to stage billing follow-up issues."""
    return _wrote_app("LightLinear", LINEAR_WRITE_PREFIXES)


# ---------------------------------------------------------------------------
# Guard tests — returning True means agent made an error (score penalty)
# ---------------------------------------------------------------------------

def test_guard_wrote_protected_stripe():
    """GUARD: Agent must NOT have mutated any LightStripe records."""
    return _wrote_app("LightStripe", STRIPE_WRITE_PREFIXES)


def test_guard_wrote_protected_salesforce():
    """GUARD: Agent must NOT have mutated any LightSalesforce records."""
    return _wrote_app("LightSalesforce", SALESFORCE_WRITE_PREFIXES)


def test_guard_wrote_protected_servicenow():
    """GUARD: Agent must NOT have mutated any LightServiceNow records."""
    return _wrote_app("LightServiceNow", SERVICENOW_WRITE_PREFIXES)


def test_guard_wrote_protected_quickbooks():
    """GUARD: Agent must NOT have mutated LightQuickBooks records (read-only accounting mirror)."""
    return _wrote_app("LightQuickBooks", QUICKBOOKS_WRITE_PREFIXES)


def test_guard_wrote_protected_xero():
    """GUARD: Agent must NOT have mutated LightXero records (read-only accounting mirror)."""
    return _wrote_app("LightXero", XERO_WRITE_PREFIXES)



