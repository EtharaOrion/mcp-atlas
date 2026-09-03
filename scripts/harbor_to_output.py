#!/usr/bin/env python3
"""Reshape a Harbor job directory (jobs/<job>/) into the per-task ``output/``
layout complex-mcp's ``--layout harbor`` writer emits, so mcp-atlas task runs
and complex-mcp task runs land in one consistent shape:

    output/<task-slug>/
    ├── config.json  lock.json  result.json          (Harbor job files, verbatim)
    ├── summary.json  pass_summary.json  pass@N.json (N = run count)  report.md
    ├── trajectory/Run_N/                            (one per trial, Harbor-shaped)
    │   ├── agent/{claude-code.jsonl, trajectory.json}
    │   ├── logs/{agent-stream.jsonl, verifier-ctrf.json, verifier-reward.txt, verifier-stdout.txt}
    │   ├── verifier/{ctrf.json, reward.txt, test-stdout.txt, reward.json, detail.json, rubric_breakdown.json}
    │   ├── artifacts/{<files the agent produced>, manifest.json, index.json}
    │   ├── config.json  lock.json  result.json  report.json
    └── .raw/trials_<slug>/                          (flat analysis tree)
        ├── summary.json  pairs.jsonl  failure_analysis.json
        ├── ground_truth/{rubric.json, gold_plan.json, efs.json, test_weights.json}   (whatever the task ships)
        └── trajectories/<model>/run_N/{agent/trajectory.json, agent/trajectory.messages.json,
              agent.log, ctrf.json, detail.json, diagnosis.json, report.json, reward.json,
              reward.txt, rubric.json, trace.jsonl, verifier/...}

mcp-atlas tasks grade two channels (traj_tests = Channel A pytest over tool
calls, rubric = Channel B LLM-judged claims). The complex-mcp-only channels
(state_completion / state_misbehave / graph_plan) have no data here and are
emitted as absent (weight 0, value null) rather than fabricated.

Usage:
    python scripts/harbor_to_output.py jobs/xenon-opus-2 [--output-dir output] [--copy-to DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "services" / "mcp_eval"))
sys.path.insert(0, str(REPO / "scripts"))

# Host-local path masking, inline. Harbor stamps absolute host paths
# (trial_uri, trials_dir) into config/result bookkeeping and writes host-side
# tracebacks into exception.txt. A path holding a repo anchor is cut to
# anchor-relative form (`/Users/x/dev/harness/output/t` -> `output/t`); any
# other home-rooted path gets its `/Users/<name>` or `/home/<name>` head
# replaced with `~`. Container paths (/workspace, /logs, /tmp) stay verbatim.
_ANCHORED_RE = re.compile(
    r"(?:file://)?(?:/(?:Users|home)|~)/[^\s\"'\\]*?/"
    r"(?=(?:delivery_output|output|input|tasks|jobs)(?:/|[\"'\s]|$))"
)
_HOME_RE = re.compile(r"(?:file://)?/(?:Users|home)/[^/\s\"'\\]+")


def mask_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    masked = _HOME_RE.sub("~", _ANCHORED_RE.sub("", text))
    if masked != text:
        path.write_text(masked, encoding="utf-8")


PASS_THRESHOLD_DEFAULT = 0.5
MCP_PREFIX = "mcp__"

# Claude Code built-ins -- not MCP tools, so they don't count as "valid" task
# tool calls but are not "invalid" either (they're always callable).
BUILTIN_TOOLS = {
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch",
    "ToolSearch", "Task", "Agent", "TodoWrite", "NotebookEdit", "Skill",
    "AskUserQuestion", "KillShell", "BashOutput", "ExitPlanMode", "EnterPlanMode",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _dump(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# Harbor artifacts we deliberately do not carry into output/. trial.log is a
# byte-identical triplicate of the job-level job.log, and lock.json only records
# the harbor invocation that produced the job — both are read during reshaping
# and dropped afterwards, never shipped.
PRUNE_FROM_OUTPUT = ("trial.log", "lock.json")

# junit.xml is read during reshaping (legacy jobs whose CTRF has no other
# source, see _junit_to_ctrf) and dropped afterwards. Tasks now emit
# verifier/ctrf.json directly via services/scoring/ctrf_pytest_plugin.py, so no
# new run produces this file at all — the prune only catches older job dirs.
PRUNE_FROM_VERIFIER = ("junit.xml", "reward_channel_a.json")


def _prune(*paths: Path) -> None:
    for pth in paths:
        try:
            pth.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"[output] could not prune {pth}: {exc}", file=sys.stderr)


def _copy(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    if dst.exists() and src.resolve() == dst.resolve():
        return True  # in-place mode: already where it belongs
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    return True


def _flatten_artifacts(run_dir: Path) -> None:
    """Lift the agent's produced files to ``Run_N/artifacts/`` and index them.

    Harbor mirrors its convention publish dir onto the host at
    ``artifacts/logs/artifacts/`` (the container path, verbatim). One level of
    nesting per run is noise, so the files are lifted to ``artifacts/`` and the
    emptied ``logs/`` subtree removed.

    Harbor's own ``manifest.json`` — the record of what collection attempted —
    is left exactly as written; it is provenance, and Harbor reserves the name.
    Alongside it goes ``index.json``: path/size/sha256 per shipped file, so a
    consumer can verify the bundle without opening it.
    """
    import hashlib

    art = run_dir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    nested = art / "logs" / "artifacts"
    if nested.is_dir():
        for child in sorted(nested.iterdir()):
            dst = art / child.name
            if dst.exists():
                # Never clobber Harbor's manifest.json (or a file already
                # lifted): keep the agent's file under a suffixed name rather
                # than dropping it silently.
                dst = art / f"{child.stem}_artifact{child.suffix}"
            shutil.move(str(child), str(dst))
        shutil.rmtree(art / "logs", ignore_errors=True)

    entries = []
    for f in sorted(p for p in art.rglob("*") if p.is_file()):
        if f.name in ("manifest.json", "index.json") and f.parent == art:
            continue
        try:
            data = f.read_bytes()
        except OSError as exc:
            print(f"[output] could not index {f}: {exc}", file=sys.stderr)
            continue
        entries.append({"path": f.relative_to(art).as_posix(), "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()})
    _dump(art / "index.json", {"files": entries, "count": len(entries),
                               "total_bytes": sum(e["size"] for e in entries)})


def _r4(x):
    return None if x is None else round(float(x), 4)


def _pct(x):
    return None if x is None else round(float(x) * 100, 2)


def _strip_mcp(name: str) -> str:
    if isinstance(name, str) and name.startswith(MCP_PREFIX):
        rest = name[len(MCP_PREFIX):]
        if "__" in rest:
            return rest.split("__", 1)[1]
    return name


def _slug(task_name: str) -> str:
    return task_name.rsplit("/", 1)[-1]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# trajectory parsing (Claude Code stream-json)
# ---------------------------------------------------------------------------

def parse_stream(path: Path) -> dict:
    """Walk the agent stream (claude-code.jsonl) once and pull out everything the reports need."""
    out = {
        "messages": [],        # flat OpenAI-shaped messages
        "trace": [],           # per tool call: step, tool, args, result, is_error
        "instruction": None,
        "final_answer": "",
        "valid": 0, "invalid": 0, "error": 0,
        "tool_cnt": {},
        "usage": None,
        "termination_reason": None,
        "thinking_blocks": 0,      # thinking blocks seen in the stream
        "thinking_nonempty": 0,    # of those, how many carried readable text
    }
    if not path.exists():
        return out
    pending: dict[str, dict] = {}
    step = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        et = ev.get("type")
        msg = ev.get("message")
        if not isinstance(msg, dict):
            # Some agents emit `message` as a bare string. Every dereference
            # below assumes a mapping, so one such event used to take down the
            # whole reshape -- after the run had already been paid for, with the
            # agent's work and its score both already on disk.
            msg = {}
        content = msg.get("content")
        if et == "assistant" and isinstance(content, list):
            texts, tcs, reasoning = [], [], []
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text"):
                    texts.append(b["text"])
                elif b.get("type") == "thinking":
                    out["thinking_blocks"] += 1
                    tt = b.get("thinking")
                    if isinstance(tt, str) and tt.strip():
                        out["thinking_nonempty"] += 1
                        reasoning.append(tt.strip())
                elif b.get("type") == "tool_use":
                    step += 1
                    raw = b.get("name", "")
                    name = _strip_mcp(raw)
                    is_mcp = raw.startswith(MCP_PREFIX)
                    rec = {"step": step, "tool": name, "raw_tool": raw, "mcp": is_mcp,
                           "arguments": b.get("input") or {}, "result": None, "is_error": False}
                    pending[b.get("id")] = rec
                    out["trace"].append(rec)
                    tcs.append({"id": b.get("id"), "type": "function",
                                "function": {"name": name, "arguments": json.dumps(b.get("input") or {})}})
            am = {"role": "assistant", "content": "\n".join(texts)}
            if reasoning:
                am["reasoning_content"] = "\n".join(reasoning)
            if tcs:
                am["tool_calls"] = tcs
            out["messages"].append(am)
        elif et == "user" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_result":
                    continue
                rc = b.get("content")
                if isinstance(rc, list):
                    rc = "\n".join(x.get("text", "") for x in rc if isinstance(x, dict) and x.get("type") == "text")
                rc = rc if isinstance(rc, str) else json.dumps(rc)
                err = bool(b.get("is_error"))
                rec = pending.get(b.get("tool_use_id"))
                if rec is not None:
                    rec["result"] = rc[:2000]
                    rec["is_error"] = err
                out["messages"].append({"role": "tool", "tool_call_id": b.get("tool_use_id"), "content": rc,
                                        **({"is_error": True} if err else {})})
        elif et == "message" and isinstance(msg, dict) and msg.get("role"):
            # OpenAI-shaped dialect (oracle / parity agent)
            role = msg.get("role")
            if role == "assistant":
                tcs = []
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    step += 1
                    raw = fn.get("name", "")
                    name = _strip_mcp(raw)
                    try:
                        args = json.loads(fn.get("arguments") or "{}") if isinstance(fn.get("arguments"), str) else (fn.get("arguments") or {})
                    except json.JSONDecodeError:
                        args = {"_raw": fn.get("arguments")}
                    rec = {"step": step, "tool": name, "raw_tool": raw, "mcp": True,
                           "arguments": args, "result": None, "is_error": False}
                    pending[tc.get("id")] = rec
                    out["trace"].append(rec)
                    tcs.append({"id": tc.get("id"), "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)}})
                am = {"role": "assistant", "content": msg.get("content") or ""}
                if tcs:
                    am["tool_calls"] = tcs
                out["messages"].append(am)
            elif role == "tool":
                rc = msg.get("content")
                rc = rc if isinstance(rc, str) else json.dumps(rc)
                rec = pending.get(msg.get("tool_call_id"))
                if rec is not None:
                    rec["result"] = rc[:2000]
                    rec["is_error"] = bool(msg.get("is_error"))
                out["messages"].append({"role": "tool", "tool_call_id": msg.get("tool_call_id"), "content": rc})
            elif role == "user":
                if out["instruction"] is None and isinstance(msg.get("content"), str):
                    out["instruction"] = msg["content"]
                out["messages"].append({"role": "user", "content": msg.get("content")})
        elif et == "user" and isinstance(content, str) and out["instruction"] is None:
            out["instruction"] = content
            out["messages"].append({"role": "user", "content": content})
        elif et == "result":
            out["final_answer"] = ev.get("result") or ""
            out["termination_reason"] = ev.get("subtype") or ("error" if ev.get("is_error") else "end")
            u = ev.get("usage") or {}
            if u:
                out["usage"] = {
                    "input_tokens": u.get("input_tokens"),
                    "output_tokens": u.get("output_tokens"),
                    "cache_read_tokens": u.get("cache_read_input_tokens"),
                    "cache_creation_tokens": u.get("cache_creation_input_tokens"),
                    "reasoning_tokens": None,
                    "cost_usd": ev.get("total_cost_usd"),
                }
    # classify calls
    for rec in out["trace"]:
        key = rec["tool"]
        bucket = out["tool_cnt"].setdefault(key, {})
        if rec["is_error"]:
            out["error"] += 1
            bucket["error"] = bucket.get("error", 0) + 1
        elif rec["mcp"]:
            out["valid"] += 1
            bucket["ok"] = bucket.get("ok", 0) + 1
        elif rec["raw_tool"] in BUILTIN_TOOLS:
            bucket["builtin"] = bucket.get("builtin", 0) + 1
        else:
            out["invalid"] += 1
            bucket["invalid"] = bucket.get("invalid", 0) + 1
    return out


def _synth_trajectory(stream: dict, *, model: str, agent_name: str, session_id, usage: dict | None) -> dict:
    """Minimal ATIF-shaped trajectory from a parsed stream (one step per
    assistant/tool/user message), for agents that don't write their own."""
    steps = []
    for i, m in enumerate(stream["messages"], 1):
        role = m.get("role")
        step = {"step_id": i, "source": "agent" if role == "assistant" else ("user" if role == "user" else "tool"),
                "message": m.get("content") or ""}
        if role == "assistant" and m.get("reasoning_content"):
            step["reasoning_content"] = m["reasoning_content"]
        if role == "assistant" and m.get("tool_calls"):
            step["tool_calls"] = [{"tool_call_id": tc.get("id"), "function_name": tc["function"]["name"],
                                   "arguments": json.loads(tc["function"].get("arguments") or "{}")}
                                  for tc in m["tool_calls"]]
        if role == "tool":
            step["observation"] = {"tool_call_id": m.get("tool_call_id"), "content": m.get("content")}
        steps.append(step)
    u = usage or {}
    return {"schema_version": "ATIF-v1.7-synth", "session_id": session_id, "trajectory_id": agent_name,
            "agent": {"name": agent_name, "version": None, "model_name": model, "extra": {"synthesized_from_stream": True}},
            "steps": steps,
            "final_metrics": {"total_prompt_tokens": u.get("input_tokens"), "total_completion_tokens": u.get("output_tokens"),
                              "total_cached_tokens": u.get("cache_read_tokens"), "total_cost_usd": u.get("cost_usd"),
                              "total_steps": len(steps), "usage": u}}


def _enabled_tools(task_dir: Path | None) -> list[str]:
    if not task_dir:
        return []
    p = task_dir / "environment" / "enabled_tools.txt"
    if p.exists():
        return [l.strip() for l in p.read_text().splitlines() if l.strip()]
    return []


# ---------------------------------------------------------------------------
# per-trial reshaping
# ---------------------------------------------------------------------------

def classify_failure(passed: bool, traj_rows: list[dict], rubric_rows: list[dict],
                     stream: dict, exception: dict | None,
                     rubric_expected: bool = False) -> tuple[str, str]:
    """Name the reason a trial failed.

    ``rubric_expected`` says the task ships a rubric. When it does but
    ``rubric_rows`` is empty, the judge never produced verdicts, so nothing here
    knows whether the answer was right -- say so instead of inferring quality
    from an empty list. Without this guard an unmounted or crashed judge reads
    as "answer correct", which is the opposite of what the evidence supports.
    """
    if exception:
        return "infrastructure", f"{exception.get('exception_type')}: {str(exception.get('exception_message'))[:160]}"
    if passed:
        return "passed", "reward met the task threshold"
    if stream["valid"] == 0 and stream["trace"]:
        return "no_mcp_tool_use", "agent never called an MCP tool (only built-ins)"
    if not stream["trace"]:
        return "no_tool_use", "agent made no tool calls at all"
    missed = [r["name"] for r in traj_rows if r.get("outcome") == "missed"]
    penal = [r["name"] for r in traj_rows if r.get("outcome") == "penalized"]
    rub_miss = [r.get("number") or r.get("id") for r in rubric_rows
                if not (r.get("outcome") == "credited" if r.get("outcome") else r.get("satisfied"))]
    if penal:
        return "guard_violation", f"guard test(s) fired: {', '.join(penal)}"
    if rubric_expected and not rubric_rows:
        detail = f"; trajectory tests also missed: {', '.join(missed)}" if missed else ""
        return "grader_incomplete", (
            "rubric judge produced no verdicts (check verifier stdout for a missing "
            "/harness/scoring mount or a judge error); answer quality is UNKNOWN" + detail)
    if missed and not rub_miss:
        return "tool_discipline", f"answer correct but required tool step(s) missing: {', '.join(missed)}"
    if rub_miss and not missed:
        return "wrong_answer", f"tool use fine but rubric claims missed: {', '.join(map(str, rub_miss))}"
    if rub_miss and missed:
        return "partial", f"missed tools {', '.join(missed)}; missed claims {', '.join(map(str, rub_miss))}"
    return "unknown", "no rule matched; inspect trajectory manually"


def _junit_to_ctrf(junit_path: Path, tw_comp: dict | None = None) -> dict | None:
    if not junit_path.exists():
        return None
    weights = (tw_comp or {}).get("tests") or {}
    try:
        tree = ET.parse(junit_path)
    except Exception:
        return None
    root = tree.getroot()
    suite = root.find("testsuite") if root.tag == "testsuites" else root
    if suite is None:
        suite = root
    tests = []
    total = passed = failed = skipped = 0
    for tc in suite.findall("testcase"):
        name = tc.get("name", "")
        duration = int(float(tc.get("time") or 0) * 1000)
        if tc.find("skipped") is not None:
            status = "skipped"; skipped += 1
        elif tc.find("failure") is not None or tc.find("error") is not None:
            status = "failed"; failed += 1
        else:
            status = "passed"; passed += 1
        total += 1
        entry: dict = {"name": name, "status": status, "duration": duration}
        w = weights.get(name)
        if w is not None:
            entry["weight"] = w
        tests.append(entry)
    # compute weighted score from positive tests (guards that "fail" = agent avoided = good)
    earned_pos = sum(weights.get(t["name"], 0) for t in tests
                     if t["status"] == "passed" and (weights.get(t["name"], 0) or 0) > 0)
    total_pos = sum(w for n, w in weights.items() if isinstance(w, (int, float)) and w > 0
                    and any(t["name"] == n and t["status"] != "skipped" for t in tests))
    overall_score = round(earned_pos / total_pos, 6) if total_pos > 0 else 0.0
    return {
        "results": {
            "tool": {"name": "pytest"},
            "summary": {"tests": total, "passed": passed, "failed": failed,
                        "pending": 0, "skipped": skipped, "other": 0,
                        "overall_score": overall_score,
                        "weighted_percentage": round(overall_score * 100, 2)},
            "tests": tests,
        }
    }


def _build_detail(ctrf: dict | None, weights: dict | None, breakdown: dict | None,
                  traj_val: float | None, rubric_val: float | None,
                  traj_w: float, rubric_w: float,
                  state_val: float | None = None, state_mis: float | None = None,
                  state_w: float = 0, mis_w: float = 0) -> dict:
    tests = ((ctrf or {}).get("results") or {}).get("tests") or []
    tw_tests = (((weights or {}).get("components") or {}).get("traj_tests") or {}).get("tests") or {}
    traj_test_rows = []
    for t in tests:
        name = t["name"]
        status = t["status"]
        raw_passed = status == "passed"
        is_skipped = status == "skipped"
        w = tw_tests.get(name, 0)
        is_positive = isinstance(w, (int, float)) and w > 0
        is_negative = isinstance(w, (int, float)) and w < 0
        if is_skipped:
            outcome = "skipped"
        elif raw_passed and is_positive:
            outcome = "credited"
        elif not raw_passed and is_positive:
            outcome = "missed"
        elif raw_passed and is_negative:
            outcome = "penalized"
        elif not raw_passed and is_negative:
            outcome = "avoided"
        else:
            outcome = "credited" if raw_passed else "missed"
        traj_test_rows.append({"name": name, "weight": w, "raw_passed": raw_passed,
                                "outcome": outcome, "is_positive": is_positive})
    rubric_rows = (breakdown.get("per_criterion") or breakdown.get("results") if breakdown else None) or []
    ledger = {
        "traj_tests": {"weight": traj_w, "value": _r4(traj_val),
                       "earned": _r4((traj_val or 0) * traj_w) if traj_val is not None else None},
        "rubric": {"weight": rubric_w, "value": _r4(rubric_val),
                   "earned": _r4((rubric_val or 0) * rubric_w) if rubric_val is not None else None},
    }
    # State channel (Rc/Rb). A declared component whose value never arrived
    # (state dump failed, or the task has no state channel) stays out rather
    # than reading as a scored zero; a declared component WITH a value must
    # appear, because a component that never scores can never fail.
    if state_w and state_val is not None:
        ledger["state_completion"] = {"weight": state_w, "value": _r4(state_val),
                                      "earned": _r4(state_val * state_w)}
    if mis_w and state_mis is not None:
        ledger["state_misbehave"] = {"weight": mis_w, "value": _r4(state_mis),
                                     "earned": _r4(state_mis * mis_w)}
    return {"ledger": ledger, "traj_test_rows": traj_test_rows, "rubric_rows": rubric_rows}


def reshape_trial(trial_dir: Path, run_no: int, *, out_task: Path, raw_trials: Path,
                  model: str, task_name: str, task_dir: Path | None, job_id: str,
                  agent_name: str = "agent") -> dict:
    slug = _slug(task_name)
    tres = _load(trial_dir / "result.json", {}) or {}
    tcfg = _load(trial_dir / "config.json", {}) or {}
    tlock = _load(trial_dir / "lock.json", {}) or {}
    ver = trial_dir / "verifier"
    ag = trial_dir / "agent"
    detail = _load(ver / "detail.json", {}) or {}
    ctrf = _load(ver / "ctrf.json")
    breakdown = _load(ver / "rubric_breakdown.json", {}) or {}
    # Rc/Rb from the task's state channel, written by tests/test_outputs.py.
    # Absent when the task has no state channel, or when its dump could not run --
    # in which case the values stay None rather than reading as a scored zero.
    state_ch = _load(ver / "state_channel.json", {}) or {}
    state_val = state_ch.get("completion") if state_ch.get("available") else None
    state_mis = state_ch.get("misbehave") if state_ch.get("available") else None
    weights = _load(task_dir / "tests" / "test_weights.json", {}) if task_dir else {}
    threshold = (weights or {}).get("threshold", PASS_THRESHOLD_DEFAULT)
    if ctrf is None and (ver / "junit.xml").exists():
        tw_comp = ((weights or {}).get("components") or {}).get("traj_tests")
        ctrf = _junit_to_ctrf(ver / "junit.xml", tw_comp)
    rubric_src_raw = _load(task_dir / "tests" / "rubric.json", []) if task_dir else []
    if isinstance(rubric_src_raw, dict):
        rubric_src_raw = rubric_src_raw.get("criteria") or []
    rubric_src = rubric_src_raw if isinstance(rubric_src_raw, list) else []

    reward = (tres.get("verifier_result") or {}).get("rewards", {}).get("reward")
    if reward is None:
        reward = _load(ver / "reward.json", {}).get("reward") if (ver / "reward.json").exists() else None
    exception = tres.get("exception_info")
    passed = reward is not None and reward >= threshold

    # The agent stream is JSON-lines, but Harbor hardcodes a .txt name
    # (harbor/agents/installed/claude_code.py tees to /logs/agent/claude-code.txt).
    # Normalize the trial file to .jsonl here; re-reshapes find the .jsonl and
    # skip the rename, so this stays idempotent.
    stream_path = ag / "claude-code.jsonl"
    legacy_txt = ag / "claude-code.txt"
    if legacy_txt.exists() and not stream_path.exists():
        legacy_txt.rename(stream_path)
    if not stream_path.exists():
        txts = sorted(ag.glob("*.txt"), key=lambda f: f.stat().st_size, reverse=True) if ag.exists() else []
        stream_path = txts[0] if txts else stream_path
    stream = parse_stream(stream_path)

    ledger = detail.get("ledger") or {}
    traj_rows = detail.get("traj_test_rows") or []
    rubric_rows = detail.get("rubric_rows") or (breakdown.get("per_criterion") or breakdown.get("results") or [])
    traj_val = (ledger.get("traj_tests") or {}).get("value")
    rubric_val = (ledger.get("rubric") or {}).get("value")
    if rubric_val is None and breakdown.get("score") is not None:
        rubric_val = breakdown["score"]
    traj_w = (ledger.get("traj_tests") or {}).get("weight", 0)
    rubric_w = (ledger.get("rubric") or {}).get("weight", 0)
    vr_rewards = (tres.get("verifier_result") or {}).get("rewards", {})
    channel_a = _load(ver / "reward_channel_a.json", {}) or {}
    if traj_val is None:
        traj_val = (
            ((channel_a.get("ledger") or {}).get("traj_tests") or {}).get("value")
            or channel_a.get("channel_a")
        )
    tw_src = (weights.get("components") or {})

    def _comp_w(name: str) -> float:
        """Declared weight for a component, 0 when the task omits it."""
        c = tw_src.get(name) or {}
        return c.get("weight", 0) if c.get("graded", True) else 0
    if traj_w == 0 and tw_src.get("traj_tests"):
        traj_w = tw_src["traj_tests"].get("weight", 0)
    if rubric_w == 0 and tw_src.get("rubric"):
        rubric_w = tw_src["rubric"].get("weight", 0)
    if rubric_val is None and rubric_w > 0:
        rubric_val = 0.0

    if not traj_rows and ctrf is not None:
        _fresh = _build_detail(ctrf, weights, breakdown, traj_val, rubric_val, traj_w, rubric_w)
        traj_rows = _fresh["traj_test_rows"]

    # ---- tokens / usage ---------------------------------------------------
    ar = tres.get("agent_result") or {}
    usage = stream["usage"] or {
        "input_tokens": ar.get("n_input_tokens"), "output_tokens": ar.get("n_output_tokens"),
        "cache_read_tokens": ar.get("n_cache_tokens"), "cache_creation_tokens": None,
        "reasoning_tokens": None, "cost_usd": ar.get("cost_usd"),
    }
    if usage.get("input_tokens") is None:
        usage["input_tokens"] = ar.get("n_input_tokens")
    if usage.get("output_tokens") is None:
        usage["output_tokens"] = ar.get("n_output_tokens")
    tool_tokens = sum(len(r["result"] or "") for r in stream["trace"]) // 4
    # Claude Code's `usage.input_tokens` excludes cache reads/creation, so the
    # headline prompt count comes from Harbor's agent_result (total input) with
    # the stream's components summed as a fallback.
    prompt_total = ar.get("n_input_tokens")
    if prompt_total is None:
        prompt_total = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_read_tokens", "cache_creation_tokens"))
    tokens = {"prompt": prompt_total or 0, "llm": usage.get("output_tokens") or ar.get("n_output_tokens") or 0, "tool": tool_tokens}

    # ---- pytest / rubric views --------------------------------------------
    test_entries = [{"name": r["name"], "weight": r.get("weight"), "passed": bool(r.get("raw_passed"))}
                    for r in traj_rows]
    n_pass = sum(1 for t in test_entries if t["passed"])
    n_skip = sum(1 for r in traj_rows if r.get("outcome") == "skipped")
    n_fail = len(test_entries) - n_pass - n_skip
    _key = lambda r: str(r.get("number") or r.get("id") or "")
    rubric_by_id = {_key(r): r for r in rubric_rows}
    bd_by_id = {_key(r): r for r in (breakdown.get("per_criterion") or breakdown.get("results") or [])}
    rubric_entries = []
    if not rubric_src and (breakdown.get("per_criterion") or breakdown.get("results")):
        _bd_list = breakdown.get("per_criterion") or breakdown.get("results") or []
        rubric_src = [{"number": r.get("number") or r.get("id") or str(i),
                       "criterion": r.get("criterion") or r.get("title") or r.get("text") or r.get("description") or "",
                       "score": r.get("score", 1) if isinstance(r.get("score"), (int, float)) and r.get("score") not in (0, 1) else 1,
                       "is_positive": r.get("is_positive", True)}
                      for i, r in enumerate(_bd_list, 1)]
    for i, c in enumerate(rubric_src, 1):
        if isinstance(c, str):
            c = {"criterion": c}
        elif not isinstance(c, dict):
            c = {}
        cid = str(c.get("number") or c.get("id") or str(i))
        row = rubric_by_id.get(cid, {})
        bd = bd_by_id.get(cid, {})
        ok = row.get("outcome") == "credited" if row.get("outcome") else bool(bd.get("satisfied") if bd else row.get("satisfied") or row.get("result"))
        w = c.get("score") or c.get("weight") or 1
        rubric_entries.append({
            "number": c.get("number") or str(i), "id": cid,
            "criterion": c.get("criterion") or c.get("text", ""),
            "type": c.get("type", "claim_coverage"),
            "evaluation_target": c.get("evaluation_target", "final_answer"),
            "importance": c.get("importance", "critical" if w >= 3 else "minor"),
            "score": w, "is_positive": c.get("is_positive", True),
            "passed": ok, "satisfied": ok, "justification": bd.get("justification", ""),
        })
    test_pct = _pct(traj_val)
    rubric_pct = _pct(rubric_val)
    try:
        _orig_rew = json.loads((ver / "reward.json").read_bytes())
    except Exception:
        _orig_rew = {}

    # The reward is the weighted ledger the verifier already computed, scaled to
    # a percentage. It is NOT recomputed here.
    #
    # This used to be `mean(test_pct, rubric_pct)`, which disagreed with the
    # graded reward in two ways at once: it dropped the per-component weights
    # from tests/test_weights.json (5 for traj_tests vs 3 for the rubric, so the
    # two channels are not equal halves), and it omitted state_completion and
    # state_misbehave entirely. On one measured trial -- channel_a 0.8485,
    # rubric 0.9595, state_completion 0.0 -- the ledger scored 0.5478 while this
    # line reported 90.4, because it averaged the two channels the agent did
    # well on and ignored the one it did not. Anything reading pass_summary.json
    # as the headline number got the flattering figure.
    _ledger_reward = _orig_rew.get("reward")
    if isinstance(_ledger_reward, (int, float)):
        final_reward = round(float(_ledger_reward) * 100, 2)
    else:
        # No reward.json (a trial that died before the verifier wrote one).
        # Fall back to the old average rather than reporting nothing, but it is
        # a strictly worse number -- see above.
        parts = [p for p in (test_pct, rubric_pct) if p is not None]
        final_reward = round(sum(parts) / len(parts), 2) if parts else None
    reward_pct_doc = {
        **_orig_rew,
        "reward": final_reward,
    }

    failure_class, failure_reason = classify_failure(
        passed, traj_rows, rubric_rows, stream, exception,
        rubric_expected=bool(rubric_src))

    reward_txt_val = str(round(final_reward, 6)) if final_reward is not None else "0.0"
    detail_doc = _build_detail(ctrf, weights, breakdown, traj_val, rubric_val, traj_w, rubric_w,
                               state_val=state_val, state_mis=state_mis,
                               state_w=_comp_w("state_completion"),
                               mis_w=_comp_w("state_misbehave"))

    # A zero with no recorded cause cannot be told apart from a harness failure,
    # so the reason travels with the number.
    #
    # The bundle's own test.sh already records one for the *unscored* case --
    # Channel A never wrote, the suite died before writing its result. It records
    # nothing for a *scored* zero, where the suite ran fine and the run genuinely
    # earned nothing. That is the common case and it arrived here unexplained.
    #
    # Written host-side into detail.json rather than into the bundle: this is the
    # field the auditor reads, and bundle bytes are hash-pinned in the ENGRAM
    # ledger, so editing them there would break the pin to add an explanation.
    # A reason the container already supplied is carried through rather than
    # overwritten -- it knows why it failed and this layer does not.
    if final_reward == 0:
        detail_doc["zero_reason"] = (
            _orig_rew.get("zero_reason") or f"{failure_class}: {failure_reason}"
        )

    if not (ag / "trajectory.json").exists() and stream["messages"]:
        # Harbor's oracle agent (and any agent that only streams a .txt) writes
        # no ATIF trajectory.json; synthesize one from the parsed stream so the
        # trajectory view is never empty.
        _dump(ag / "trajectory.json", _synth_trajectory(stream, model=model, agent_name=agent_name,
                                                         session_id=tres.get("id"), usage=usage))

    # ---- trajectory/Run_N (Harbor-shaped) ---------------------------------
    run_dir = out_task / "trajectory" / f"Run_{run_no}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if _copy(ag / "claude-code.jsonl", run_dir / "agent" / "claude-code.jsonl"):
        # Drop the stale .txt twin a pre-rename reshape may have left behind.
        (run_dir / "agent" / "claude-code.txt").unlink(missing_ok=True)
    _copy(ag / "oracle.txt", run_dir / "agent" / "oracle.txt")
    _copy(ag / "trajectory.json", run_dir / "agent" / "trajectory.json")
    for f in ("config.json", "result.json"):
        if _copy(trial_dir / f, run_dir / f):
            # Harbor stamps absolute host paths (trial_uri, trials_dir) into
            # these; mask them so nothing downstream can ship a /Users/... path.
            mask_file(run_dir / f)
    # Harbor's exception.txt is a host-side Python traceback (frames under the
    # user's home dir); mask it wherever it has landed in this run folder.
    for exc_f in run_dir.glob("exception.txt"):
        mask_file(exc_f)
    _trun_res = _load(run_dir / "result.json", {}) or {}
    if isinstance((_trun_res.get("verifier_result") or {}).get("rewards"), dict):
        _trun_res["verifier_result"]["rewards"]["reward"] = reward_pct_doc.get("reward", final_reward)
        _dump(run_dir / "result.json", _trun_res)
    _copy(trial_dir / "artifacts", run_dir / "artifacts")
    _flatten_artifacts(run_dir)
    if _copy(stream_path, run_dir / "logs" / "agent-stream.jsonl"):
        (run_dir / "logs" / "agent-stream.txt").unlink(missing_ok=True)
    _copy(ver / "ctrf.json", run_dir / "logs" / "verifier-ctrf.json")
    _copy(ver / "reward.txt", run_dir / "logs" / "verifier-reward.txt")
    _copy(ver / "test-stdout.txt", run_dir / "logs" / "verifier-stdout.txt")
    # Light-servers fleet logs (health report + tool calls), staged into
    # /logs/light-servers by tests/test.sh from the shared server_logs volume.
    # They are their own files, not a slice of verifier-stdout.txt: that one is
    # a copy of /logs/verifier/test-stdout.txt, which is the pytest redirect.
    _copy(ver / "light-servers-health.log",
          run_dir / "logs" / "light-servers-health.log")
    _copy(ver / "light-servers-tool_calls.log",
          run_dir / "logs" / "light-servers-tool-calls.log")
    for f in ("ctrf.json", "reward.json", "test-stdout.txt", "detail.json",
              "rubric_breakdown.json", "judge_tokens.json",
              "state_channel.json", "end_env.json"):
        _copy(ver / f, run_dir / "verifier" / f)
    vdir = run_dir / "verifier"
    vdir.mkdir(parents=True, exist_ok=True)
    ldir = run_dir / "logs"
    ldir.mkdir(parents=True, exist_ok=True)
    if ctrf is not None and not (vdir / "ctrf.json").exists():
        _dump(vdir / "ctrf.json", ctrf)
    if ctrf is not None and not (ldir / "verifier-ctrf.json").exists():
        _dump(ldir / "verifier-ctrf.json", ctrf)
    if not (ldir / "verifier-reward.txt").exists():
        (ldir / "verifier-reward.txt").write_text(reward_txt_val + "\n", encoding="utf-8")
    if not (vdir / "detail.json").exists():
        _dump(vdir / "detail.json", detail_doc)
    _dump(vdir / "reward.json", reward_pct_doc)
    _rbd = _load(vdir / "rubric_breakdown.json", {}) or {}
    if _rbd:
        for _k in ("score", "rc", "rb"):
            _rbd.pop(_k, None)
        _dump(vdir / "rubric_breakdown.json", _rbd)
    report = {
        "model": model, "run_index": run_no, "include_multimodal": False,
        "pytest": {"passed": n_pass, "failed": n_fail, "skipped": n_skip,
                   "exit_code": 0 if n_fail == 0 else 1,
                   "reward": _pct(traj_val), "tests": test_entries},
        "rubric": rubric_entries,
        "final_reward": final_reward,
        "test_weights_percentage": test_pct,
        "rubric_weights_percentage": rubric_pct,
        "thinking": {"blocks": stream["thinking_blocks"],
                     "with_text": stream["thinking_nonempty"]},
    }
    _dump(run_dir / "report.json", report)
    if stream["thinking_blocks"] and not stream["thinking_nonempty"]:
        # Signature-only thinking blocks: the model thought but the request
        # shape suppressed the text (thinking display omitted). Run with
        # thinking=adaptive + thinking_display=summarized to capture it.
        print(f"[harbor_to_output] WARNING: {stream['thinking_blocks']} thinking "
              f"blocks in run {run_no} all came back empty (display omitted?)",
              file=sys.stderr)

    # ---- .raw/trials_<slug>/trajectories/<model>/run_N --------------------
    raw_run = raw_trials / "trajectories" / model / f"run_{run_no}"
    raw_run.mkdir(parents=True, exist_ok=True)
    _copy(ag / "trajectory.json", raw_run / "agent" / "trajectory.json")
    _dump(raw_run / "agent" / "trajectory.messages.json", {
        "session_id": tres.get("id"), "timestamp": tres.get("finished_at"),
        "meta_info": {"platform": "linux", "task": task_name, "model": model},
        "messages": stream["messages"],
    })
    _copy(stream_path, raw_run / "agent.log")
    for f in ("ctrf.json", "detail.json", "reward.json"):
        _copy(ver / f, raw_run / f)
    _copy(ver, raw_run / "verifier")
    rver = raw_run / "verifier"
    rver.mkdir(parents=True, exist_ok=True)
    if ctrf is not None and not (raw_run / "ctrf.json").exists():
        _dump(raw_run / "ctrf.json", ctrf)
    if ctrf is not None and not (rver / "ctrf.json").exists():
        _dump(rver / "ctrf.json", ctrf)

    if not (raw_run / "detail.json").exists():
        _dump(raw_run / "detail.json", detail_doc)
    if not (rver / "detail.json").exists():
        _dump(rver / "detail.json", detail_doc)
    _dump(rver / "reward.json", reward_pct_doc)
    _dump(raw_run / "rubric.json", {"format": "criteria", "rubric_score": _r4(rubric_val), "per_criterion": rubric_entries})
    with (raw_run / "trace.jsonl").open("w", encoding="utf-8") as fh:
        for r in stream["trace"]:
            fh.write(json.dumps({"step": r["step"], "tool": r["tool"], "arguments": r["arguments"],
                                 "result": r["result"], "is_error": r["is_error"]}, ensure_ascii=False) + "\n")
    diagnosis = {
        "failure_class": failure_class, "reason": failure_reason,
        "evidence": {"valid_calls": stream["valid"], "invalid_calls": stream["invalid"],
                     "error_calls": stream["error"],
                     "recall": sum(1 for r in traj_rows if r.get("outcome") == "credited" and (r.get("weight") or 0) > 0),
                     "total": sum(1 for r in traj_rows if (r.get("weight") or 0) > 0),
                     "misbehave": sum(1 for r in traj_rows if r.get("outcome") == "penalized"),
                     "rubric_credited": sum(1 for r in rubric_entries if r["passed"]),
                     "rubric_total": len(rubric_entries),
                     "enabled_tools": _enabled_tools(task_dir)},
    }
    _dump(raw_run / "diagnosis.json", diagnosis)
    raw_report = {
        "task": task_name, "model": model, "seed": None, "attempt": run_no,
        "passed": passed, "reward": final_reward, "final_score": final_reward,
        "final_score_basis": "weighted(traj_tests+rubric)" if (traj_w or rubric_w) else "rubric",

        "channel_a_present": bool(traj_rows),
        "test_weights_percentage": test_pct, "rubric_weights_percentage": rubric_pct,
        "rubric_rc": _r4(rubric_val), "rubric_rb": None,
        "rubric_per_criterion": rubric_entries,
        "tokens": tokens, "usage": usage,
        "tool_summary": {"tool_cnt": stream["tool_cnt"], "valid_tool_calls": stream["valid"],
                         "invalid_tool_calls": stream["invalid"], "error_tool_calls": stream["error"]},
        "termination_reason": stream["termination_reason"],
        "threshold": threshold,
    }
    _dump(raw_run / "report.json", raw_report)

    # ---- episode record for summary.json ----------------------------------
    goal_rows = [r for r in traj_rows if (r.get("weight") or 0) > 0]
    judge = {
        "reward": final_reward, "passed": passed,
        "quadrant": "PASSED" if passed else "FAILED", "threshold": threshold,
        "components": {
            "traj_tests": {"weight": traj_w, "value": _pct(traj_val),
                           "earned": _r4((traj_val or 0) * traj_w) if traj_val is not None else None},
            "rubric": {"weight": rubric_w, "value": _pct(rubric_val),
                       "earned": _r4((rubric_val or 0) * rubric_w) if rubric_val is not None else None},
            # Weights come from tests/test_weights.json rather than being pinned
            # to 0 here. Nothing in this pipeline computes their values yet, so
            # value/earned stay None; a task that declares them non-zero will at
            # least surface the discrepancy instead of silently reading as 0.
            "state_completion": {"weight": _comp_w("state_completion"), "value": _pct(state_val),
                                 "earned": _r4((state_val or 0) * _comp_w("state_completion"))
                                 if state_val is not None else None},
            "state_misbehave": {"weight": _comp_w("state_misbehave"), "severity": _r4(state_mis),
                                "penalty": _r4((state_mis or 0) * abs(_comp_w("state_misbehave")))
                                if state_mis is not None else None},
            "graph_plan": {"weight": _comp_w("graph_plan"), "value": None, "earned": None},
        },
        "basis": [k for k in ["traj_tests", "rubric", "state_completion", "state_misbehave", "graph_plan"] if _comp_w(k) != 0],
        "recall": sum(1 for r in goal_rows if r.get("outcome") == "credited"),
        "total": len(goal_rows),
        "misbehave": sum(1 for r in traj_rows if r.get("outcome") == "penalized"),
        "state": _pct(state_val), "plan": None,
        "traj_tests": {"recall": sum(1 for r in goal_rows if r.get("outcome") == "credited"),
                       "total": len(goal_rows),
                       "misbehave": sum(1 for r in traj_rows if r.get("outcome") == "penalized"),
                       "passed_tests": {r["name"]: bool(r.get("raw_passed")) for r in traj_rows}},
        "rubric_score": _pct(rubric_val),
        "rubric_per_criterion": rubric_entries,
        "grader": "weighted(" + "+".join(k for k in ["traj_tests", "rubric", "state_completion", "state_misbehave", "graph_plan"] if _comp_w(k) != 0) + ")",
    }
    episode = {
        "index": run_no, "name": task_name, "passed": passed, "gradeable": reward is not None,
        "judge": judge,
        "valid_tool_calls": stream["valid"], "invalid_tool_calls": stream["invalid"],
        "error_tool_calls": stream["error"],
        "tokens": tokens, "usage": usage,
        "dir": str(Path(slug) / ".raw" / f"trials_{slug}" / "trajectories" / model / f"run_{run_no}"),
        "trial_name": tres.get("trial_name") or trial_dir.name,
        "failure_class": failure_class, "failure_reason": failure_reason,
        "exception": exception,
    }
    pair = {"task": task_name, "seed": None, "attempt": run_no,
            "instruction": stream["instruction"] or ((task_dir / "instruction.md").read_text() if task_dir and (task_dir / "instruction.md").exists() else None),
            "final_answer": stream["final_answer"], "reward": final_reward, "passed": passed}
    per_run = {"run_index": run_no, "include_multimodal": False,
               "test_weights_percentage": test_pct, "rubric_weights_percentage": rubric_pct,
               "combined_score": final_reward}
    # Safe here: ctrf was resolved at the top of this function, so a legacy
    # XML-only job still reshapes correctly — it just does not ship the XML.
    _prune(*(run_dir / f for f in PRUNE_FROM_OUTPUT),
           *(run_dir / "logs" / f for f in PRUNE_FROM_OUTPUT),
           *(run_dir / "verifier" / f for f in PRUNE_FROM_VERIFIER),
           *(raw_run / "verifier" / f for f in PRUNE_FROM_VERIFIER),
           *(raw_run / f for f in PRUNE_FROM_VERIFIER))
    return {"episode": episode, "pair": pair, "per_run": per_run, "report": report,
            "failure": {"attempt": run_no, "failure_class": failure_class, "reason": failure_reason}}


# ---------------------------------------------------------------------------
# pass@k
# ---------------------------------------------------------------------------

def _comb(n, k):
    from math import comb
    return comb(n, k)


def pass_at_k(n: int, c: int, k: int) -> float:
    if n == 0 or k > n:
        return 0.0
    if n - c < k:
        return 1.0
    return 1.0 - _comb(n - c, k) / _comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    if n == 0 or k > n:
        return 0.0
    return _comb(c, k) / _comb(n, k) if c >= k else 0.0


def wilson_ci(c: int, n: int, z: float = 1.96):
    if n == 0:
        return [0.0, 0.0]
    p = c / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(max(0.0, centre - half), 6), round(min(1.0, centre + half), 6)]


# ---------------------------------------------------------------------------
# job-level
# ---------------------------------------------------------------------------

def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 6) if vals else 0.0


def _mean_or_none(vals):
    """Mean of the measured values, or None when nothing was measured.

    `_mean` returns 0.0 for an empty list, which reports an unmeasured channel
    as a scored zero. For counts and token totals that is harmless -- no tokens
    really is zero tokens. For a scored component it is not: a channel that
    produced no value and a channel that scored 0.0 are different facts, and
    collapsing them is the same confusion the reward ledger already refuses.
    Aggregates over scored components use this instead.
    """
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 6) if vals else None


def _fmt_metric(value, places: int = 4) -> str:
    """Render an aggregate for report.md, naming an absent one rather than
    printing a number that was never measured."""
    return "unmeasured" if value is None else f"{value:.{places}f}"


def convert_job(job_dir: Path, output_root: Path, *, ks: list[int], run_offset: int = 0) -> list[Path]:
    job_cfg = _load(job_dir / "config.json", {}) or {}
    job_res = _load(job_dir / "result.json", {}) or {}
    job_lock = _load(job_dir / "lock.json", {}) or {}
    agents = job_cfg.get("agents") or [{}]
    agent_name = agents[0].get("name") or "agent"
    model = agents[0].get("model_name") or agent_name   # oracle runs have no model
    job_id = job_res.get("id") or job_dir.name

    if not agents[0].get("name"):
        # `harbor run --agent oracle` leaves job config.json without an agents
        # block; the trial's own config/result carry it.
        cands = [p for p in job_dir.iterdir() if p.is_dir()]
        if (job_dir / "trajectory").is_dir():
            cands += [p for p in (job_dir / "trajectory").iterdir() if p.is_dir()]
        for p in cands:
            a = ((_load(p / "config.json", {}) or {}).get("agent")
                 or ((_load(p / "result.json", {}) or {}).get("config") or {}).get("agent") or {})
            if a.get("name"):
                agent_name = a["name"]; model = a.get("model_name") or agent_name
                break
    # group trial dirs by task
    trials = sorted(p for p in job_dir.iterdir()
                    if p.is_dir() and p.name not in ("trajectory", ".raw") and (p / "config.json").exists())
    traj_root = job_dir / "trajectory"
    if traj_root.is_dir():
        trials += sorted(
            (p for p in traj_root.iterdir()
             if p.is_dir() and (p / "config.json").exists() and not re.match(r'^Run_\d+$', p.name)),
            key=lambda p: int(p.name.split("_")[-1]) if p.name.split("_")[-1].isdigit() else 0)
    by_task: dict[str, list[Path]] = {}
    for t in trials:
        cfg = _load(t / "config.json", {}) or {}
        tpath = (cfg.get("task") or {}).get("path")
        tname = (cfg.get("task") or {}).get("name")
        tdir = Path(tpath) if tpath else None
        if tdir and not tdir.is_absolute():
            tdir = (REPO / tdir)
        if not tname:
            toml = _load_task_name(tdir) if tdir else None
            tname = toml or (tdir.name if tdir else t.name.split("__")[0])
        by_task.setdefault(tname, []).append(t)

    written = []
    for task_name, tdirs in by_task.items():
        slug = _slug(task_name)
        cfg0 = _load(tdirs[0] / "config.json", {}) or {}
        tpath = (cfg0.get("task") or {}).get("path")
        task_dir = Path(tpath) if tpath else None
        if task_dir and not task_dir.is_absolute():
            task_dir = REPO / task_dir
        if task_dir and not task_dir.exists():
            task_dir = None

        out_task = output_root / slug
        in_place = out_task.exists() and out_task.resolve() == job_dir.resolve()
        if in_place:
            # Harbor wrote the job straight into output/<slug>/ (the shim passes
            # --jobs-dir output --job-name <slug>). Reshape it where it stands:
            # each trial dir becomes trajectory/Run_N, nothing is copied twice.
            moved = []
            for i, t in enumerate(tdirs):
                dst = out_task / "trajectory" / f"Run_{i + 1 + run_offset}"
                if t.resolve() != dst.resolve():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.move(str(t), str(dst))
                moved.append(dst)
            tdirs = moved
        else:
            if out_task.exists():
                shutil.rmtree(out_task)
            out_task.mkdir(parents=True)
        raw_trials = out_task / ".raw" / f"trials_{slug}"
        if raw_trials.exists() and run_offset == 0:
            shutil.rmtree(raw_trials)
        raw_trials.mkdir(parents=True, exist_ok=True)

        for f in ("config.json", "result.json"):
            _copy(job_dir / f, out_task / f)
        # ground truth the task ships
        if task_dir:
            for f in ("rubric.json", "gold_plan.json", "efs.json", "test_weights.json", "test_outputs.py", "gt_env.json"):
                _copy(task_dir / "tests" / f, raw_trials / "ground_truth" / f)
            _copy(task_dir / "instruction.md", raw_trials / "ground_truth" / "instruction.md")
            _copy(task_dir / "environment" / "enabled_tools.txt", raw_trials / "ground_truth" / "enabled_tools.txt")

        recs = [reshape_trial(t, i + 1 + run_offset, out_task=out_task, raw_trials=raw_trials, model=model,
                              task_name=task_name, task_dir=task_dir, job_id=job_id, agent_name=agent_name)
                for i, t in enumerate(tdirs)]
        eps = [r["episode"] for r in recs]
        if run_offset > 0:
            prev_summary = _load(out_task / "summary.json", {}) or {}
            prev_eps = prev_summary.get("episodes") or []
            all_eps = prev_eps + eps
        else:
            all_eps = eps
        n = len(all_eps)
        c = sum(1 for e in all_eps if e["passed"])
        rewards = [e["judge"]["reward"] for e in all_eps]
        hist: dict[str, int] = {}
        for e in all_eps:
            hist[e["failure_class"]] = hist.get(e["failure_class"], 0) + 1
        stamp = _now()

        # result.json's per-trial metrics are the record an auditor re-derives
        # the summary aggregates from, so they are loaded and normalised BEFORE
        # summary.json is built and the aggregates average those exact values.
        # Deriving an aggregate from a host-side component instead is what left
        # avg_completion_rate reporting 0.0 next to per-trial records of 0.9 and
        # 0.714: one name held two different quantities, so the rollup a reader
        # sees said the runs completed nothing while the records beside it said
        # 90% and 71%.
        _top_res = _load(out_task / "result.json", {}) or {}
        _evals = ((_top_res.get("stats") or {}).get("evals") or {})
        _per_trial: list[dict] = []
        if _evals and all_eps:
            for _eval_data in _evals.values():
                _metrics = _eval_data.get("metrics") or []
                # Extend rather than truncate. The incoming metrics list can be
                # shorter than the episode list, and the previous guard silently
                # dropped every episode past its end, so a two-trial run recorded
                # one per-trial block and no aggregate could be re-derived from it.
                while len(_metrics) < len(all_eps):
                    _metrics.append({})
                _eval_data["metrics"] = _metrics
                for _i, _ep in enumerate(all_eps):
                    _metrics[_i]["reward"] = _ep["judge"]["reward"]
                _new_rstats: dict = {"reward": {}}
                for _i, _ep in enumerate(all_eps):
                    _tname = _ep.get("trial_name") or f"trial_{_i}"
                    if _i < len(_metrics):
                        for _fld in ("reward",):
                            _v = str(_metrics[_i].get(_fld, 0))
                            _new_rstats[_fld].setdefault(_v, []).append(_tname)
                _eval_data["reward_stats"] = _new_rstats
                _per_trial.extend(_metrics)

        # summary.json
        summary = {
            "run_id": job_dir.name, "timestamp": stamp,
            "config": {"model": model, "agent": agent_name, "method": "harbor", "benchmark": "mcp-atlas",
                       "task_dir": str(task_dir) if task_dir else None,
                       "image": _load_image(task_dir), "episodes": n,
                       "harbor_job": str(job_dir)},
            "metrics": {
                "accuracy": _mean([1.0 if e["passed"] else 0.0 for e in all_eps]),
                "avg_reward": _mean(rewards),
                # avg_completion_rate and avg_misbehave_rate average the per-trial
                # values recorded in result.json, because those are the bytes the
                # aggregate is checked against. An earlier attempt pointed this at
                # the Channel A traj_tests value on the assumption that the
                # per-trial completion_rate carried it; it does not -- that field
                # comes from the container's verifier/reward.json, so the two
                # never reconciled and traj_tests being unmeasured then published
                # a confident 0.0.
                "avg_completion_rate": _mean_or_none(
                    [m.get("completion_rate") for m in _per_trial]),
                "avg_rubric_score": _mean([e["judge"]["rubric_score"] for e in all_eps]),
                "avg_rc": _mean([e["judge"]["state"] for e in all_eps]),
                "avg_rb": _mean([(e["judge"]["components"].get("state_misbehave") or {}).get("severity") or 0.0 for e in all_eps]),
                # Unmeasured stays unmeasured: when Channel A produced no value
                # this reports None rather than a 0.0 that reads as "scored, and
                # scored nothing".
                "avg_traj_tests": _mean_or_none(
                    [e["judge"]["components"]["traj_tests"]["value"] for e in all_eps]),
                "avg_misbehave_rate": _mean_or_none(
                    [m.get("misbehave_rate") for m in _per_trial]),
                "avg_valid_tool_calls": _mean([e["valid_tool_calls"] for e in all_eps]),
                "avg_invalid_tool_calls": _mean([e["invalid_tool_calls"] for e in all_eps]),
                "avg_error_tool_calls": _mean([e["error_tool_calls"] for e in all_eps]),
                "avg_prompt_tokens": _mean([e["tokens"]["prompt"] for e in all_eps]),
                "avg_llm_tokens": _mean([e["tokens"]["llm"] for e in all_eps]),
                "avg_tool_tokens": _mean([e["tokens"]["tool"] for e in all_eps]),
            },
            "episodes": all_eps,
        }
        _dump(out_task / "summary.json", summary)
        # Normalisation happened above, before the aggregates were computed from
        # it; this only persists the result.
        if _evals and all_eps:
            _dump(out_task / "result.json", _top_res)

        # pass_summary.json
        per_run = [r["per_run"] for r in recs]
        if run_offset > 0:
            prev_ps = _load(out_task / "pass_summary.json", {}) or {}
            per_run = (prev_ps.get("per_run") or []) + per_run
        pass_summary = {
            "model": model, "runs": n,
            "average_combined_score": _mean([p["combined_score"] for p in per_run]),
            "average_test_weights_percentage": _mean([p["test_weights_percentage"] for p in per_run]),
            "average_rubric_weights_percentage": (_mean(_rp) if (_rp := [p["rubric_weights_percentage"] for p in per_run if p["rubric_weights_percentage"] is not None]) else None),
            "per_run": per_run,
        }
        _dump(out_task / "pass_summary.json", pass_summary)

        # passk_summary.json
        # n/c from the summary-episode merge can undercount: the merge only
        # sees episodes summary.json carried forward, so a task with five
        # Run_N dirs on disk can still report n=1. The Run_N dirs are the
        # ground truth for how many attempts exist -- each holds its own
        # verifier/reward.json -- so when disk shows more runs than the merge
        # recovered, recount n and c from disk.
        _traj_dir = out_task / "trajectory"
        _disk_rewards = []
        if _traj_dir.is_dir():
            for _rd in sorted(_traj_dir.glob("Run_*"),
                              key=lambda p: int(p.name.split("_")[-1]) if p.name.split("_")[-1].isdigit() else 0):
                _rw = _load(_rd / "verifier" / "reward.json", {}) or {}
                if _rw.get("reward") is not None:
                    _disk_rewards.append(float(_rw["reward"]))
        if len(_disk_rewards) > n:
            _tw = (_load(task_dir / "tests" / "test_weights.json", {}) if task_dir else {}) or {}
            _thr = _tw.get("threshold", PASS_THRESHOLD_DEFAULT)
            n = len(_disk_rewards)
            c = sum(1 for r in _disk_rewards if r >= _thr)
            rewards = _disk_rewards
        # Empty ks means "auto": scale k to however many runs this task has
        # actually accumulated, so pass@k needs no --at retuning when the
        # attempt count changes.
        ks_eff = list(range(1, n + 1)) if not ks else ([k for k in ks if k <= n] or [1])
        per_task = [{
            "task": task_name, "n": n, "c": c,
            "pass@1": round(pass_at_k(n, c, 1), 6),
            "pass@k": {str(k): round(pass_at_k(n, c, k), 6) for k in ks_eff},
            "pass^k": {str(k): round(pass_hat_k(n, c, k), 6) for k in ks_eff},
            "mean_reward_per_trial": _mean(rewards),
            "failure_breakdown": hist,
        }]
        passk = {
            "model": model, "tasks": 1, "passed": c, "accuracy": round(c / n, 6) if n else 0.0,
            "mean_reward_per_trial": _mean(rewards),
            "mean_pass@k": per_task[0]["pass@k"], "mean_pass^k": per_task[0]["pass^k"],
            "failure_mode_histogram": hist, "per_task": per_task,
            "attempts_per_task": n, "at": ks_eff,
        }
        # The pass@k file is named after the accumulated run count
        # (pass@1.json, pass@2.json, ...) so the filename itself says how many
        # runs it covers. Drop any stale copy from a previous run count.
        passk_name = f"pass@{n}.json"
        for _old in list(out_task.glob("pass@*.json")) + [out_task / "passk_summary.json"]:
            if _old.name != passk_name and _old.exists():
                _old.unlink()
        _dump(out_task / passk_name, passk)
        _dump(raw_trials / "passk_summary.json", passk)

        # .raw summary / pairs / failure_analysis
        _dump(raw_trials / "summary.json", {
            "task": task_name, "model": model, "agent": agent_name, "seed": None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metrics": {"n": n, "c": c, "pass@1": round(pass_at_k(n, c, 1), 6),
                        "p_hat": round(c / n, 6) if n else 0.0, "ci95": wilson_ci(c, n),
                        "pass@k": per_task[0]["pass@k"], "pass^k": per_task[0]["pass^k"],
                        "failure_breakdown": hist},
            "attempts": [{"attempt": e["index"], "passed": e["passed"], "reward": e["judge"]["reward"],
                          "rubric_score": e["judge"]["rubric_score"],
                          "traj_tests": e["judge"]["components"]["traj_tests"]["value"],
                          "failure_class": e["failure_class"]} for e in eps],
        })
        with (raw_trials / "pairs.jsonl").open("w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r["pair"], ensure_ascii=False) + "\n")
        _dump(raw_trials / "failure_analysis.json", [r["failure"] for r in recs])

        # report.md
        m = summary["metrics"]
        lines = [
            f"# Benchmark Report — {slug}", "",
            f"- Timestamp: {stamp}", f"- Model: `{model}`", f"- Agent: `{agent_name}`",
            f"- Method: `harbor`", f"- Benchmark: `mcp-atlas`", f"- Harbor job: `{job_dir}`",
            f"- Episodes: {n}", "",
            "## Aggregate metrics", "", "| Metric | Value |", "|---|---|",
            f"| Accuracy (reward ≥ threshold) | {m['accuracy']:.4f} |",
            f"| Avg reward | {m['avg_reward']:.4f} |",
            f"| Avg rubric (Channel B) | {m['avg_rubric_score']:.4f} |",
            f"| Avg traj_tests (Channel A) | {_fmt_metric(m['avg_traj_tests'])} |",
            f"| Avg misbehave rate | {_fmt_metric(m['avg_misbehave_rate'])} |",
            f"| Avg valid tool calls / episode | {m['avg_valid_tool_calls']:.4f} |",
            f"| Avg invalid tool calls / episode | {m['avg_invalid_tool_calls']:.4f} |",
            f"| Avg error tool calls / episode | {m['avg_error_tool_calls']:.4f} |",
            f"| Avg prompt tokens | {m['avg_prompt_tokens']:.2f} |",
            f"| Avg llm tokens | {m['avg_llm_tokens']:.2f} |",
            f"| Avg tool tokens | {m['avg_tool_tokens']:.2f} |", "",
            "## Per-episode", "",
            "| # | Passed | Reward | Traj recall / total | Misbehave | Rubric | Valid TC | Invalid TC | Failure | Dir |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for e in eps:
            j = e["judge"]
            lines.append(
                f"| {e['index']} | {'✓' if e['passed'] else '✗'} | {j['reward']} | {j['recall']} / {j['total']} | "
                f"{j['misbehave']} | {sum(1 for r in j['rubric_per_criterion'] if r['passed'])} / {len(j['rubric_per_criterion'])} | "
                f"{e['valid_tool_calls']} | {e['invalid_tool_calls']} | `{e['failure_class']}` | `{e['dir']}` |")
        lines += ["", "## Channel A — trajectory tests (per run)", ""]
        for r in recs:
            lines.append(f"### Run {r['report']['run_index']}")
            lines.append("")
            lines.append("| Test | Weight | Passed |")
            lines.append("|---|---|---|")
            for t in r["report"]["pytest"]["tests"]:
                lines.append(f"| {t['name']} | {t['weight']} | {'✓' if t['passed'] else '✗'} |")
            lines.append("")
        lines += ["## Channel B — rubric claims (run 1)", "", "| # | Claim | Passed |", "|---|---|---|"]
        for c_ in recs[0]["report"]["rubric"]:
            lines.append(f"| {c_['number']} | {c_['criterion']} | {'✓' if c_['passed'] else '✗'} |")
        (out_task / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Harbor writes lock.json straight into the job dir (which is out_task on
        # in-place runs). Everything that needs it has been read by now.
        _prune(*(out_task / f for f in PRUNE_FROM_OUTPUT))
        written.append(out_task)
        print(f"[output] {task_name}: {n} run(s), passed {c}/{n}, mean reward {_mean(rewards)} → {out_task}")
    return written


def _load_task_name(task_dir: Path | None):
    if not task_dir:
        return None
    p = task_dir / "task.toml"
    if not p.exists():
        return None
    m = re.search(r'^\s*name\s*=\s*"([^"]+)"', p.read_text(), re.M)
    return m.group(1) if m else None


def _load_image(task_dir: Path | None):
    if not task_dir:
        return None
    p = task_dir / "task.toml"
    if not p.exists():
        return None
    m = re.search(r'^\s*image\s*=\s*"([^"]+)"', p.read_text(), re.M)
    return m.group(1) if m else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("job_dir", type=Path, help="Harbor job directory, e.g. jobs/xenon-opus-2")
    ap.add_argument("--output-dir", type=Path, default=REPO / "output")
    ap.add_argument("--copy-to", type=Path, default=None,
                    help="Also mirror each output/<task>/ dir into this directory.")
    ap.add_argument("--at", default="auto",
                    help="comma-separated k values for pass@k, or 'auto' (default) "
                         "to use every k from 1 to the number of runs")
    ap.add_argument("--run-offset", type=int, default=0, dest="run_offset",
                    help="number of already-written Run_N dirs to skip when numbering new runs")
    a = ap.parse_args(argv)
    ks = [] if a.at.strip().lower() == "auto" else [int(x) for x in a.at.split(",") if x.strip()]
    if not a.job_dir.exists():
        print(f"job dir not found: {a.job_dir}", file=sys.stderr)
        return 2
    written = convert_job(a.job_dir, a.output_dir, ks=ks, run_offset=a.run_offset)
    # Mask host-local paths (/Users/..., /home/..., file:///...) in EVERYTHING
    # this pipeline leaves behind, not just the delivery: the reshaped task
    # dir (config/summary/report.md carry jobs_dir and task paths) and
    # harbor's own raw job records (trial_uri etc.). By reshape time the
    # harbor run is complete, and masking keeps the JSON valid, so `harbor
    # view` still works. Runs before copy_to so mirrors ship masked too.
    _md_script = Path(__file__).parent / "make_delivery.py"
    _mod = None
    if _md_script.exists():
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("make_delivery", _md_script)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        for w in written:
            _mod.mask_tree(w)
        if written:
            _mod.mask_tree(a.job_dir)
    if a.copy_to:
        for w in written:
            dst = a.copy_to / w.name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(w, dst)
            print(f"[output] mirrored → {dst}")
    if _mod is not None and written:
        _delivery_dir = a.output_dir.parent / "delivery_output"
        for w in written:
            _mod.make_delivery(w.name, a.output_dir, REPO / "tasks", _delivery_dir)
            print(f"[delivery] {w.name} → {_delivery_dir / w.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
