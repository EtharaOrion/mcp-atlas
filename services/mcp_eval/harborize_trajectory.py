#!/usr/bin/env python3
"""Repackage a flat-CSV run_eval.py trajectory into the Harbor-native output
directory shape (result.json / report.json / judge_response.txt / config.json /
lock.json under output/trajectory/Run N/, plus job-level files under output/
and output/logs/), the same layout a real `harbor run` job produces.

Why this exists: `output/harbor/<task_id>/task.toml` targets a native MCP
server (streamable-http on :18765) that the ghcr.io/scaleapi/mcp-atlas:1.2.7
image does not actually expose (it only serves a custom REST API -
POST /call-tool, POST /list-tools - on :1984). That makes a real `harbor run`
against these task bundles fail at the environment healthcheck before the
agent ever starts. Until that's fixed with a real MCP-protocol adapter, this
script gets you Harbor-shaped *output* from the CSV pipeline that already
works end-to-end (run_all.sh + run_eval.py).

What's real vs. reconstructed:
  - The agent response / tool-call trace: REAL. Taken verbatim from a genuine
    run_eval.py trajectory (an actual model run through the litellm proxy /
    ccbridge chain against live MCP servers).
  - The verifier verdict: REAL, but lighter-weight than Harbor's own judge.
    tests/agent_judge.py normally runs the full claude-agent-sdk agent (with
    Read/Bash/Grep tools) against the criteria; that needs the `claude` CLI +
    claude-agent-sdk installed. This script instead sends the *exact same*
    CRITERIA / AGENT_PROMPT / EVALUATION_PROMPT_TEMPLATE / OUTPUT_SCHEMA
    (loaded directly from the task's own agent_judge.py, not copied by hand)
    as a single structured-output call through the same litellm proxy. Same
    rubric, same prompt, real LLM call - just without the judge's own file-
    reading tool loop.
  - Directory/timestamp/job metadata: reconstructed to match the shape Harbor
    itself writes (cf. model-training-ckpt-codec-recovery/output/), using
    real timestamps pulled from the source run's own log/output file mtimes.
"""
import argparse
import csv
import json
import runpy
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load_judge_module(judge_path: Path) -> dict:
    """Execute agent_judge.py's module-level code (not __main__) to pull the
    real CRITERIA/AGENT_PROMPT/EVALUATION_PROMPT_TEMPLATE/OUTPUT_SCHEMA/
    aggregate_score without hand-copying them (avoids drift)."""
    return runpy.run_path(str(judge_path), run_name="harborize_import")


def csv_row(csv_path: Path, task_id: str) -> dict:
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            if row["task_id"] == task_id:
                return row
    raise SystemExit(f"task_id {task_id} not found in {csv_path}")


def to_trajectory_jsonl(raw_conversation_history: str, final_response: str) -> str:
    """Convert run_eval.py's OpenAI-style message list into the line-JSON
    ('type' per line, final line type=='result') shape agent_judge.py's own
    find_agent_trajectory_filepath()/extract_agent_response() expect, so a
    real agent_judge.py run (if claude-agent-sdk is later installed) could
    consume this file as-is."""
    lines = []
    try:
        messages = json.loads(raw_conversation_history)
    except (json.JSONDecodeError, TypeError):
        messages = []
    for msg in messages:
        lines.append(json.dumps({"type": "message", "message": msg}))
    lines.append(json.dumps({"type": "result", "result": final_response}))
    return "\n".join(lines) + "\n"


def run_judge_via_proxy(judge_mod: dict, agent_prompt: str, agent_response: str,
                         trajectory_path: str, proxy_base: str, api_key: str,
                         model: str) -> tuple:
    import urllib.request
    import urllib.error

    criteria = judge_mod["CRITERIA"]
    template = judge_mod["EVALUATION_PROMPT_TEMPLATE"]
    schema = judge_mod["OUTPUT_SCHEMA"]
    aggregate_score = judge_mod["aggregate_score"]

    eval_prompt = template.substitute(
        agent_prompt=agent_prompt,
        agent_response=agent_response,
        criteria_json=json.dumps(criteria, indent=2),
        trajectory_path=trajectory_path,
    )
    eval_prompt += (
        "\n\nRespond with ONLY a JSON object matching this schema (no prose, no markdown fences):\n"
        + json.dumps(schema["schema"], indent=2)
    )

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": eval_prompt}],
    }).encode()

    req = urllib.request.Request(
        f"{proxy_base}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Judge call failed: {e.code} {e.read().decode()[:500]}")

    text = payload["choices"][0]["message"]["content"].strip()
    if text.startswith("```"):
        parts = text.split("\n")
        parts = parts[1:]
        if parts and parts[-1].strip() == "```":
            parts = parts[:-1]
        text = "\n".join(parts)
    parsed = json.loads(text)
    results = parsed.get("results", []) if isinstance(parsed, dict) else parsed

    agg_score = aggregate_score(results)
    criteria_by_id = {c["id"]: c for c in criteria}
    verified = []
    for r in results:
        crit = criteria_by_id.get(r.get("id"), {})
        verified.append({
            **crit,
            "score": r.get("score", 0.0),
            "result": r.get("score") == 1.0,
            "justification": r.get("justification", ""),
        })
    return agg_score, verified, payload.get("usage", {})


def iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + "Z"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-id", default="688a441c1a0d2e5c93853e76")
    ap.add_argument("--csv", default="output/outputs_task_688a441c.csv")
    ap.add_argument("--harbor-task-dir", default="output/harbor/688a441c1a0d2e5c93853e76")
    ap.add_argument("--model", default="claude-opus-5", help="agent model label (display only)")
    ap.add_argument("--proxy-model", default="anthropic/claude-sonnet-5",
                     help="litellm model name to use for the judge call")
    ap.add_argument("--proxy-base", default="http://127.0.0.1:4000")
    ap.add_argument("--proxy-key", default="litellm-stub-key")
    ap.add_argument("--started-at", type=float, default=None,
                     help="unix ts; defaults to the source CSV's mtime minus 200s")
    ap.add_argument("--finished-at", type=float, default=None,
                     help="unix ts; defaults to the source CSV's mtime")
    args = ap.parse_args()

    csv_path = REPO / args.csv
    harbor_dir = REPO / args.harbor_task_dir
    judge_path = harbor_dir / "tests" / "agent_judge.py"

    finished_at = args.finished_at or csv_path.stat().st_mtime
    started_at = args.started_at or (finished_at - 202)  # observed sandbox+run wall time

    row = csv_row(csv_path, args.task_id)
    agent_response = row["response"]

    judge_mod = load_judge_module(judge_path)
    agent_prompt = judge_mod["AGENT_PROMPT"]

    out_root = harbor_dir / "output"
    trial_suffix = uuid.uuid4().hex[:7]
    trial_name = f"{args.task_id[:20]}__{trial_suffix}"
    run_dir = out_root / "trajectory" / "Run 1"
    (run_dir / "agent" / "sessions").mkdir(parents=True, exist_ok=True)
    (run_dir / "verifier").mkdir(parents=True, exist_ok=True)
    (out_root / "logs").mkdir(parents=True, exist_ok=True)

    trajectory_file = run_dir / "agent" / "sessions" / f"{trial_name}.txt"
    trajectory_file.write_text(to_trajectory_jsonl(row["raw_conversation_history"], agent_response))

    print(f"Running judge ({args.proxy_model} via {args.proxy_base}) ...", file=sys.stderr)
    agg_score, verified, usage = run_judge_via_proxy(
        judge_mod, agent_prompt, agent_response, str(trajectory_file),
        args.proxy_base, args.proxy_key, args.proxy_model,
    )
    print(f"Judge done. aggregate_score={agg_score}", file=sys.stderr)

    job_id = str(uuid.uuid4())
    trial_id = str(uuid.uuid4())

    # ---- verifier/ ----
    (run_dir / "verifier" / "reward.txt").write_text(str(agg_score))
    (run_dir / "verifier" / "reward.json").write_text(json.dumps({"reward": agg_score}, indent=2))
    (run_dir / "verifier" / "rubric_breakdown.json").write_text(
        json.dumps({"score": agg_score, "results": verified}, indent=2)
    )

    # ---- trajectory/Run 1/judge_response.txt (human-readable judge transcript) ----
    lines = [f"Judge model: {args.proxy_model} (via litellm proxy -> ccbridge -> api.anthropic.com)",
             f"Criteria count: {len(verified)}", ""]
    for r in verified:
        status = "PASS" if r.get("result") else "FAIL"
        lines.append(f"[{status}] {r.get('id')}: {r.get('title', '')}")
        lines.append(f"  justification: {r.get('justification', '')}")
        lines.append("")
    lines.append(f"Aggregate score (all_pass): {agg_score}")
    (run_dir / "judge_response.txt").write_text("\n".join(lines))

    # ---- trajectory/Run 1/report.json ----
    report = {
        "model": args.model,
        "run_index": 1,
        "include_multimodal": False,
        "rubric": {
            "aggregator": "all_pass",
            "reward": agg_score,
            "criteria": verified,
        },
        "provenance": {
            "note": ("Repackaged from a flat-CSV run_eval.py trajectory, not a live `harbor run` "
                      "container execution - the mcp-atlas image serves a custom REST API on :1984, "
                      "not the native MCP streamable-http server task.toml's healthcheck expects on "
                      ":18765, so `harbor run` cannot currently drive this task end-to-end."),
            "source_csv": str(csv_path.relative_to(REPO)),
            "judge_method": ("Direct structured-output call through the litellm proxy using the exact "
                              "CRITERIA/AGENT_PROMPT/OUTPUT_SCHEMA from tests/agent_judge.py, not the "
                              "full claude-agent-sdk agentic judge (which needs the claude CLI + "
                              "claude-agent-sdk installed in-container)."),
        },
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2))

    # ---- trajectory/Run 1/config.json + lock.json ----
    trial_cfg = {
        "task": {"path": str(harbor_dir.relative_to(REPO))},
        "trial_name": trial_name,
        "trials_dir": str(out_root.relative_to(REPO)),
        "agent_setup_timeout_multiplier": 6.0,
        "agent": {"name": "run_eval.py", "model_name": args.model},
        "job_id": job_id,
    }
    (run_dir / "config.json").write_text(json.dumps(trial_cfg, indent=2))

    trial_lock = {
        "schema_version": 1,
        "task": {
            "name": args.task_id,
            "type": "local",
            "path": str(harbor_dir.relative_to(REPO)),
        },
        "install_only": False,
        "timeout_multiplier": 1.0,
        "agent_setup_timeout_multiplier": 6.0,
        "agent": {
            "name": "run_eval.py",
            "model_name": args.model,
            "skills": [],
            "resume_trajectory": False,
            "extra_allowed_hosts": [],
            "kwargs": {},
            "mcp_servers": [],
        },
        "environment": {"type": "docker-compose (mcp-atlas run_all.sh)", "force_build": False},
        "verifier": {"disable": False},
    }
    (run_dir / "lock.json").write_text(json.dumps(trial_lock, indent=2))

    # ---- trajectory/Run 1/result.json ----
    trial_result = {
        "id": trial_id,
        "task_name": f"mcp-atlas/{args.task_id}",
        "trial_name": trial_name,
        "trial_uri": f"file://{run_dir}",
        "task_id": {"path": str(harbor_dir.relative_to(REPO))},
        "source": "MCP-Atlas.parquet",
        "config": trial_cfg,
        "agent_info": {"name": "run_eval.py", "version": None, "model_info": {"name": args.model, "provider": "anthropic"}},
        "agent_result": {
            "n_input_tokens": usage.get("prompt_tokens"),
            "n_cache_tokens": None,
            "n_output_tokens": usage.get("completion_tokens"),
            "cost_usd": None,
            "rollout_details": None,
            "metadata": {"raw_conversation_history_chars": len(row["raw_conversation_history"])},
        },
        "verifier_result": {"rewards": {"reward": agg_score}},
        "exception_info": None,
        "started_at": iso(started_at),
        "finished_at": iso(finished_at),
        "environment_setup": {"started_at": iso(started_at), "finished_at": iso(started_at + 164)},
        "agent_setup": None,
        "agent_execution": {"started_at": iso(started_at + 164), "finished_at": iso(finished_at)},
        "verifier": {"started_at": iso(finished_at), "finished_at": iso(finished_at)},
        "step_results": None,
    }
    (run_dir / "result.json").write_text(json.dumps(trial_result, indent=2))

    # ---- output/config.json, lock.json, result.json, pass_summary.json ----
    job_cfg = {
        "job_name": f"{args.task_id[:20]}-{trial_suffix}",
        "jobs_dir": str(out_root.relative_to(REPO)),
        "agent_setup_timeout_multiplier": 6.0,
        "n_concurrent_trials": 1,
        "agents": [{"name": "run_eval.py", "model_name": args.model}],
        "tasks": [{"path": str(harbor_dir.relative_to(REPO))}],
    }
    (out_root / "config.json").write_text(json.dumps(job_cfg, indent=2))

    job_lock = dict(trial_lock)
    job_lock = {
        "schema_version": 2,
        "created_at": iso(started_at),
        "harbor": {"version": "n/a (harborize_trajectory.py repackaging, not a live harbor run)", "is_editable": False},
        "n_concurrent_trials": 1,
        "trials": [trial_lock],
    }
    (out_root / "lock.json").write_text(json.dumps(job_lock, indent=2))

    job_result = {
        "id": job_id,
        "started_at": iso(started_at),
        "updated_at": iso(finished_at),
        "finished_at": iso(finished_at),
        "n_total_trials": 1,
        "stats": {
            "n_completed_trials": 1,
            "n_errored_trials": 0,
            "n_running_trials": 0,
            "n_pending_trials": 0,
            "n_cancelled_trials": 0,
            "n_retries": 0,
            "evals": {
                f"run_eval.py__{args.model}__adhoc": {
                    "n_trials": 1,
                    "n_errors": 0,
                    "metrics": [{"mean": agg_score}],
                    "pass_at_k": {},
                    "reward_stats": {"reward": {str(agg_score): [trial_name]}},
                    "exception_stats": {},
                }
            },
            "n_input_tokens": usage.get("prompt_tokens"),
            "n_cache_tokens": None,
            "n_output_tokens": usage.get("completion_tokens"),
            "cost_usd": None,
        },
    }
    (out_root / "result.json").write_text(json.dumps(job_result, indent=2))

    pass_summary = {
        "model": args.model,
        "runs": 1,
        "average_combined_score": round(agg_score * 100, 2),
        "average_test_weights_percentage": None,
        "average_rubric_weights_percentage": round(agg_score * 100, 2),
        "per_run": [{
            "run_index": 1,
            "include_multimodal": False,
            "rubric_weights_percentage": round(agg_score * 100, 2),
            "combined_score": round(agg_score * 100, 2),
        }],
    }
    (out_root / "pass_summary.json").write_text(json.dumps(pass_summary, indent=2))

    # ---- output/logs/* (mirrors the job-*.json naming Harbor itself uses) ----
    for name, obj in [("job-config.json", job_cfg), ("job-lock.json", job_lock),
                       ("job-result.json", job_result), ("pass-summary.json", pass_summary)]:
        (out_root / "logs" / name).write_text(json.dumps(obj, indent=2))
    (out_root / "logs" / "INDEX.md").write_text(
        "# Job output index\n\n"
        f"- `job-config.json` / `job-lock.json` / `job-result.json` / `pass-summary.json` - job-level.\n"
        f"- `trajectory/Run 1/` - single trial: config.json, lock.json, result.json, report.json, "
        f"judge_response.txt, agent/sessions/{trial_name}.txt, verifier/{{reward.txt,reward.json,rubric_breakdown.json}}.\n\n"
        "This tree was produced by `services/mcp_eval/harborize_trajectory.py`, which repackages a "
        "flat-CSV `run_eval.py` trajectory into this shape - see `trajectory/Run 1/report.json`'s "
        "`provenance` field for exactly what's real vs. reconstructed.\n"
    )

    print(f"\nWrote Harbor-shaped output to: {out_root.relative_to(REPO)}")
    print(f"Reward: {agg_score}  ({sum(1 for r in verified if r.get('result'))}/{len(verified)} criteria passed)")


if __name__ == "__main__":
    main()
