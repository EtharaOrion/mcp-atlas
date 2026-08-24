#!/bin/bash
set -e

python3 - <<'PYEOF'
import json, pathlib, re

log = pathlib.Path("/logs/agent/claude-code.txt")
traj_file = pathlib.Path("/tmp/agent_trajectory.json")
steps = []
final_message = ""
pending = {}

for line in (log.read_text().splitlines() if log.exists() else []):
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        continue
    etype = ev.get("type")
    if etype == "assistant":
        msg = ev.get("message") or {}
        content = msg.get("content") or []
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tid = block.get("id", "")
                pending[tid] = {"tool": block.get("name", ""), "arguments": block.get("input") or {}, "response": None}
            elif block.get("type") == "text" and block.get("text"):
                final_message = block["text"]
    elif etype == "user":
        msg = ev.get("message") or {}
        content = msg.get("content") or []
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tid = block.get("tool_use_id", "")
            if tid not in pending:
                continue
            raw = block.get("content")
            if isinstance(raw, list) and raw:
                raw = raw[0].get("text", "") if isinstance(raw[0], dict) else str(raw[0])
            try:
                resp = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                resp = {"text": str(raw)}
            pending[tid]["response"] = resp
            steps.append(pending.pop(tid))
    elif etype == "result":
        r = ev.get("result", "")
        if isinstance(r, str) and r:
            final_message = r

traj_file.write_text(json.dumps({"steps": steps, "final_message": final_message}, indent=2))
print(f"[trajectory] {len(steps)} steps → {traj_file}")
PYEOF

JUDGE_CLI=/harness/scoring/rubric_judge_cli.py
if [ ! -f "$JUDGE_CLI" ]; then
    echo "FATAL: scoring harness not mounted -- $JUDGE_CLI is absent." >&2
    echo "       Check the /harness/scoring volume in environment/docker-compose.yaml." >&2
    exit 2
fi

if ! python3 "$JUDGE_CLI" \
    --rubric /tests/rubric.json \
    --trajectory /tmp/agent_trajectory.json \
    --output /logs/verifier/rubric_breakdown.json \
    --token-output /logs/verifier/judge_tokens.json; then
    echo "ERROR: rubric judge ran but failed; rubric channel is UNSCORED for this trial." >&2
    mkdir -p /logs/verifier
    echo "rubric judge failed at run time; rubric_breakdown.json was not produced" \
        > /logs/verifier/rubric_judge_failed.txt
fi

# State channel: read the agent's own world back out of light-servers before the
# tests run. Reuses the session_id the trajectory records, because a fresh login
# would roll a pristine world and show us nothing. Best-effort -- if it produces
# no file, test_world_ends_correct skips exactly as it did before.
COMPLEXMCP_TRAJECTORY=/tmp/agent_trajectory.json \
    python3 /tests/state_dump.py || echo "WARNING: state dump failed; state channel will skip" >&2

COMPLEXMCP_TRAJECTORY=/tmp/agent_trajectory.json PYTHONPATH=/tests python3 -m pytest /tests/test_outputs.py \
    --junitxml=/logs/verifier/junit.xml -v || true

python3 - <<'EOF'
import json, pathlib

channel_a = pathlib.Path("/logs/verifier/reward_channel_a.json")
reward_out = pathlib.Path("/logs/verifier/reward.json")
reward_out.parent.mkdir(parents=True, exist_ok=True)

if channel_a.exists():
    data = json.loads(channel_a.read_text())
    out = {
        "reward": float(data.get("reward", 0.0)),
        "completion_rate": float(data.get("completion_rate", 0.0)),
        "misbehave_rate": float(data.get("misbehave_rate", 0.0)),
    }
else:
    out = {"reward": 0.0, "completion_rate": 0.0, "misbehave_rate": 0.0}

reward_out.write_text(json.dumps(out, indent=2))
print("reward.json written:", out)
EOF
