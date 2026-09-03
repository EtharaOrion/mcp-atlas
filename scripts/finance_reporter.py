#!/usr/bin/env python3
"""
finance_reporter.py — report one run's token/cost usage to the Odoo Finance API.

Called at the end of scripts/run_task.sh, after harbor_to_output.py has
reshaped the Harbor job:

    run_task.sh -> harbor_to_output.py -> finance_reporter.py -> Odoo Finance API

    scripts/finance_reporter.py --run-dir output/<task>/trajectory/Run_1 \
                                --task-id <task-slug>

Data sources (all already on disk when this runs):
    <run-dir>/result.json                 tokens, cost, model, trial name, timing
    <run-dir>/agent/trajectory.json       cache-token split
    <run-dir>/verifier/judge_tokens.json  judge_lines (written by rubric_judge_cli)
    <job-dir>/summary.json                run config (model/agent), if present
    tools.claude_account                  subscription_id, fetched once and cached

Environment (read from the process env, falling back to the nearest .env
at or above the repo root):
    ODOO_URL           https://<odoo-instance>   (unset => skip, exit 0)
    ODOO_AUTH_TOKEN    sent as "Authorization: Bearer <token>"
                       (header/scheme overridable via ODOO_AUTH_HEADER/_SCHEME)
    FINANCE_PROJECT_ID       e.g. PRJ-512   (required to report)
    FINANCE_PROJECT_TYPE     default "Technical"
    FINANCE_TEAM_TYPE        default "Projects"
    FINANCE_BUDGET_TYPE      "RFP" or "Production"
    FINANCE_RFP_SUB_TYPE     "Testing" | "Sampling"  (RFP only)
    FINANCE_PRODUCTION_MODE  "Singlephase" | "Multiphase"  (Production only)
    FINANCE_PHASE_NUMBER     default "1"; Odoo's handler requires it
    (is_phase_based is not sent — triggers a server-side schema error on current Odoo build)

Odoo field set (verified against a live create on the current build): it
stores judge_input_tokens, judge_output_tokens, judge_input_cache_tokens,
judge_output_cache_tokens, judge_cost_usd and drops judge_cache_write_tokens
and judge_turns. Both are still sent so they land if the schema catches up; the
cache-write value is carried by judge_output_cache_tokens meanwhile, which is
why that column holds an input-side write rather than an output count.

Exits 0 even when reporting fails: a finance outage must never fail a task run.
Pass --strict to exit non-zero instead (useful in CI).

Token mapping
-------------
Harbor reports prompt tokens as a total that already contains the cached
tokens, while the Finance API wants the buckets side by side. To keep the sum
intact and avoid double counting:

    trajectory_input_tokens        = total_prompt - cache_read - cache_creation
    trajectory_input_cache_tokens  = cache_read      (served from cache)
    trajectory_output_cache_tokens = cache_creation  (written to cache)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENDPOINT_PATH = "api/v1/ethara_project/trajectory_usage/create"
RETRIES = 3
TIMEOUT_SEC = 30

RFP_SUB_TYPES = ("Testing", "Sampling")
PRODUCTION_MODES = ("Singlephase", "Multiphase")


# --------------------------------------------------------------------- config
def find_dotenv() -> Path | None:
    """First .env at or above the repo root.

    The harness is often vendored as a subdirectory of a larger workspace that
    owns the single .env (ODOO_URL, FINANCE_*). Looking only at REPO/.env made
    stage_finance skip silently in that layout, so walk up instead.
    """
    for parent in (REPO, *REPO.parents):
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_dotenv() -> None:
    """Fill os.environ from the nearest .env for keys that aren't already set."""
    path = find_dotenv()
    if path is None:
        return
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if val and val[0] not in "\"'":
            val = val.split(" #", 1)[0].split("\t#", 1)[0].strip()   # inline comment
        val = val.strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def log(msg: str, err: bool = False) -> None:
    print(f"[finance] {msg}", file=sys.stderr if err else sys.stdout)


# ------------------------------------------------------------------ read files
def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def num(value, default=0):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return int(n) if n.is_integer() else n


def iso8601(raw, fallback_mtime: float | None = None) -> str:
    """Normalize a Harbor timestamp to ISO 8601 in UTC.

    Odoo drops the offset and reads the wall clock it is given as UTC, so
    sending local time shifted every record by the reporter's own offset
    (a 12:38 +05:30 run displayed as 18:08). Emitting UTC makes the value Odoo
    stores and the instant the run finished the same moment.
    """
    dt = None
    if isinstance(raw, str) and raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            dt = None
    if dt is None and fallback_mtime is not None:
        dt = datetime.fromtimestamp(fallback_mtime)
    if dt is None:
        dt = datetime.now()
    if dt.tzinfo is None:            # naive stamps are local wall clock
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def judge_lines(run_dir: Path) -> list[dict]:
    """judge_tokens.json as written by rubric_judge_cli.py --token-output."""
    raw = read_json(run_dir / "verifier" / "judge_tokens.json")
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = raw.get("judge_lines") or [raw]
    if not isinstance(raw, list):
        return []
    keys = ("judge_input_tokens", "judge_output_tokens", "judge_input_cache_tokens",
            "judge_output_cache_tokens", "judge_cost_usd")
    out = []
    for rec in raw:
        if isinstance(rec, dict):
            line = {"model_name": str(rec.get("model_name") or "")}
            line.update({k: num(rec.get(k, 0)) for k in keys})
            # Cache WRITES, input-side, billed at 1.25x -- not output tokens.
            # `judge_output_cache_tokens` is the pre-rename name and is still
            # accepted so runs recorded before the rename keep reporting.
            line["judge_cache_write_tokens"] = num(
                rec.get("judge_cache_write_tokens",
                        rec.get("judge_output_cache_tokens", 0)))
            line["judge_turns"] = num(rec.get("judge_turns", 0))
            out.append(line)
    return out


def usage_evidence(run_dir: Path) -> str:
    """"" if the run finished; otherwise why its usage cannot be trusted.

    usage_for_run() reads result.json and agent/trajectory.json and falls back
    to 0 for anything missing, so a directory whose run is still in flight
    builds a perfectly well-formed all-zeros payload. Posting that is how a
    trajectory ends up in Finance reading 0 tokens and $0.00 with no model
    name. Refuse by default and let --allow-empty override, so a genuinely
    free trial (the oracle agent reports null tokens) can still be recorded
    on purpose rather than by accident.
    """
    if not (run_dir / "result.json").is_file():
        return "no result.json — the run has not finished"
    result = read_json(run_dir / "result.json")
    if result is None:
        return "result.json is unreadable"
    traj = read_json(run_dir / "agent" / "trajectory.json") or {}
    if result.get("agent_result") is None and not traj.get("final_metrics"):
        exc = (result.get("exception_info") or {}).get("exception_type")
        return (f"no agent_result and no final_metrics"
                + (f" (run raised {exc})" if exc else " — the run did not produce usage"))
    return ""


def usage_for_run(run_dir: Path) -> dict:
    """Model, tokens, cost and timing for one Run_N directory."""
    result = read_json(run_dir / "result.json") or {}
    traj = read_json(run_dir / "agent" / "trajectory.json") or {}
    metrics = traj.get("final_metrics") or {}
    extra = metrics.get("extra") or {}
    agent_result = result.get("agent_result") or {}

    prompt = num(metrics.get("total_prompt_tokens", agent_result.get("n_input_tokens")))
    completion = num(metrics.get("total_completion_tokens", agent_result.get("n_output_tokens")))
    cache_read = num(extra.get("total_cache_read_input_tokens",
                               metrics.get("total_cached_tokens",
                                           agent_result.get("n_cache_tokens"))))
    cache_write = num(extra.get("total_cache_creation_input_tokens", 0))
    cost = num(metrics.get("total_cost_usd", agent_result.get("cost_usd")), 0.0)

    fresh = prompt - cache_read - cache_write
    if fresh < 0:                      # cache counted outside the total
        fresh = prompt

    # job-level summary.json is two levels up: Run_N -> trajectory -> <job>
    summary = read_json(run_dir.parent.parent / "summary.json") or {}
    model = (((result.get("agent_info") or {}).get("model_info") or {}).get("name")
             or (traj.get("agent") or {}).get("model_name")
             or ((result.get("config") or {}).get("agent") or {}).get("model_name")
             or ((summary.get("config") or {}).get("model"))
             or env("MODEL"))

    stamp = result.get("finished_at") or result.get("updated_at") or result.get("started_at")
    return {
        "trajectory_id": result.get("trial_name") or run_dir.name,
        "generated_at": iso8601(stamp, run_dir.stat().st_mtime),
        "model_name": model,
        "trajectory_input_tokens": fresh,
        "trajectory_output_tokens": completion,
        "trajectory_input_cache_tokens": cache_read,
        "trajectory_output_cache_tokens": cache_write,
        "trajectory_cost_usd": cost,
    }


# ------------------------------------------------------------------- payload
def budget_fields() -> dict:
    """Apply the documented budget_type rules; raise on a bad combination."""
    budget = env("FINANCE_BUDGET_TYPE", "RFP")
    if budget not in ("RFP", "Production"):
        raise ValueError(f"FINANCE_BUDGET_TYPE must be 'RFP' or 'Production', got {budget!r}")
    if budget == "RFP":
        sub = env("FINANCE_RFP_SUB_TYPE", "Testing")
        if sub not in RFP_SUB_TYPES:
            raise ValueError(f"FINANCE_RFP_SUB_TYPE must be one of {RFP_SUB_TYPES}, got {sub!r}")
        return {"budget_type": budget, "rfp_sub_type": sub,
                "production_mode": ""}
    mode = env("FINANCE_PRODUCTION_MODE")
    if mode not in PRODUCTION_MODES:
        raise ValueError(f"FINANCE_PRODUCTION_MODE must be one of {PRODUCTION_MODES} "
                         f"when FINANCE_BUDGET_TYPE=Production, got {mode!r}")
    return {"budget_type": budget, "rfp_sub_type": "",
            "production_mode": mode}


def build_payload(run_dir: Path, task_id: str, account: dict) -> dict:
    project_id = env("FINANCE_PROJECT_ID")
    if not project_id:
        raise ValueError("FINANCE_PROJECT_ID is required (e.g. PRJ-512)")

    usage = usage_for_run(run_dir)
    payload = {
        "project_id": project_id,
        "project_type": env("FINANCE_PROJECT_TYPE", "Technical"),
        "task_id": task_id,
        "trajectory_id": usage["trajectory_id"],
        "team_type": env("FINANCE_TEAM_TYPE", "Projects"),
    }
    payload.update(budget_fields())
    payload["generated_at"] = usage["generated_at"]
    payload["model_name"] = usage["model_name"]
    for key in ("trajectory_input_tokens", "trajectory_output_tokens",
                "trajectory_input_cache_tokens", "trajectory_output_cache_tokens",
                "trajectory_cost_usd"):
        payload[key] = usage[key]
    payload["subscription_id"] = (env("FINANCE_SUBSCRIPTION_ID")
                                  or account.get("subscription_id") or "")
    # Odoo's handler requires phase_number even though the API doc omits it,
    # and wants it as a string.
    payload["phase_number"] = env("FINANCE_PHASE_NUMBER", "1")
    payload["judge_lines"] = judge_lines(run_dir)
    return payload


# ---------------------------------------------------------------------- http
def headers() -> dict:
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    token = env("ODOO_AUTH_TOKEN")
    if token:
        name = env("ODOO_AUTH_HEADER", "Authorization")
        scheme = env("ODOO_AUTH_SCHEME", "Bearer")
        hdrs[name] = f"{scheme} {token}".strip()
    extra = env("ODOO_EXTRA_HEADERS")
    if extra:
        try:
            hdrs.update({str(k): str(v) for k, v in json.loads(extra).items()})
        except Exception as exc:
            log(f"warning: ODOO_EXTRA_HEADERS is not a JSON object ({exc})", err=True)
    return hdrs


def post(url: str, payload: dict) -> tuple[int, str]:
    body = json.dumps(payload).encode()
    last = ""
    for attempt in range(1, RETRIES + 1):
        req = urllib.request.Request(url, data=body, headers=headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                return resp.status, resp.read().decode(errors="replace")[:2000]
        except urllib.error.HTTPError as exc:
            text = exc.read().decode(errors="replace")[:2000]
            if exc.code < 500 and exc.code != 429:
                return exc.code, text                   # client error: no retry
            last = f"HTTP {exc.code}: {text}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        if attempt < RETRIES:
            time.sleep(2 ** (attempt - 1))
    return 0, last


# ---------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Report one run's usage to the Finance API")
    ap.add_argument("--run-dir", required=True,
                    help="output/<task>/trajectory/Run_N")
    ap.add_argument("--task-id", default="",
                    help="finance task id (defaults to the job directory name)")
    ap.add_argument("--dry-run", action="store_true", help="print the payload, send nothing")
    ap.add_argument("--odoo-url", default="", help="override ODOO_URL")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero on failure (default: always exit 0)")
    ap.add_argument("--allow-empty", action="store_true",
                    help="post even when the run produced no usage (e.g. an oracle "
                         "trial); by default an unfinished run is refused")
    ap.add_argument("--skip-if-reported", action="store_true",
                    help="exit 0 without posting if this run already has a successful "
                         "finance_receipt.json (makes a resumed run safe to re-drive)")
    args = ap.parse_args()

    load_dotenv()
    fail = 1 if args.strict else 0

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        log(f"no such run dir: {run_dir}", err=True)
        return fail

    if not args.allow_empty:
        why = usage_evidence(run_dir)
        if why:
            log(f"refusing to report {run_dir.name}: {why}. "
                f"Re-run once the trial finishes, or pass --allow-empty to record "
                f"it as a zero-usage trial.", err=True)
            return fail

    # Posting is the one step here with an off-machine side effect, so a resumed
    # or re-driven run must not report the same trajectory twice. The receipt the
    # previous attempt wrote is the proof it already landed; a receipt from a
    # FAILED post is not, and falls through to a retry.
    if args.skip_if_reported:
        prior = run_dir / "finance_receipt.json"
        try:
            if prior.is_file() and json.loads(prior.read_text()).get("ok"):
                log(f"{run_dir.name} already reported ({prior.name}) — skipping")
                return 0
        except (OSError, json.JSONDecodeError):
            pass  # unreadable receipt proves nothing; report again

    base = (args.odoo_url or env("ODOO_URL")).rstrip("/")
    if not base and not args.dry_run:
        log("ODOO_URL not set — skipping usage report")
        return 0
    url = f"{base}/{ENDPOINT_PATH}" if base else "(dry-run)"

    task_id = args.task_id or run_dir.parent.parent.name

    try:
        from tools.claude_account import get_claude_account_info
    except ImportError:
        sys.path.insert(0, str(REPO))
        from tools.claude_account import get_claude_account_info

    account = get_claude_account_info()
    if account.get("error"):
        log(f"warning: Claude account lookup failed ({account['error']}) — "
            f"subscription_id falls back to FINANCE_SUBSCRIPTION_ID", err=True)

    try:
        payload = build_payload(run_dir, task_id, account)
    except ValueError as exc:
        log(f"cannot build payload: {exc}", err=True)
        return fail

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    if not env("ODOO_AUTH_TOKEN") and not env("ODOO_EXTRA_HEADERS"):
        log("warning: ODOO_AUTH_TOKEN is empty — sending unauthenticated", err=True)

    status, text = post(url, payload)
    ok = 200 <= status < 300
    log(f"{run_dir.name} {payload['trajectory_id']} "
        f"${payload['trajectory_cost_usd']} sub={payload['subscription_id'] or '(none)'} "
        f"-> {'ok' if ok else 'FAILED'} ({status or 'no response'})"
        + ("" if ok else f": {text}"), err=not ok)

    receipt = {"run_dir": str(run_dir), "endpoint": url, "http_status": status,
               "ok": ok, "response": text, "posted_at": iso8601(None),
               "account_source": account.get("source"), "payload": payload}
    try:
        (run_dir / "finance_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    except OSError as exc:
        log(f"warning: could not write receipt ({exc})", err=True)

    # The receipt lives inside the job dir, and Harbor deletes that wholesale
    # when the same --job-name is run again -- taking the only proof of the
    # post with it. Append a one-line summary somewhere Harbor does not own,
    # so what was billed stays auditable across re-runs.
    ledger = Path(env("FINANCE_LEDGER") or (REPO / "output" / "finance_ledger.jsonl"))
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a") as fh:
            fh.write(json.dumps({
                "posted_at": receipt["posted_at"], "ok": ok, "http_status": status,
                "task_id": task_id, "trajectory_id": payload["trajectory_id"],
                "model_name": payload["model_name"],
                "trajectory_cost_usd": payload["trajectory_cost_usd"],
                "run_dir": str(run_dir),
            }) + "\n")
    except OSError as exc:
        log(f"warning: could not append to ledger ({exc})", err=True)

    return 0 if ok else fail


if __name__ == "__main__":
    sys.exit(main())
