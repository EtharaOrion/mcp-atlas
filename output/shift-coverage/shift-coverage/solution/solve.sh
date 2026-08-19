#!/bin/bash
# Oracle solution: replay the reference trajectory so the verifier grades a
# perfect run. See adapters/mcp_atlas/adapter.py.
set -euo pipefail

mkdir -p /logs/agent

python3 - <<'PYEOF' > /logs/agent/oracle.txt
import json

claims = ["The response states that 4 night shifts were staffed by personnel without the 'night' certification.", 'The response lists the non-compliant shift ids as SH-1003, SH-1006, SH-1010 and SH-1014.', 'The response reports the total uncovered hours as 38.', 'The response identifies S-02 (Tomas Okafor), S-04 (Dara Whitfield) and S-06 (Jonah Behrends) as the uncertified staff involved.', 'The response does not flag any day shift as non-compliant.', 'The response does not flag any shift staffed by S-01, S-03 or S-05, all of whom hold the night certification.']
tool_calls = [{'name': 'filesystem_list_directory', 'arguments': {'path': '/data/task_data/rosters'}, 'rationale': 'Discover the roster files -- the prompt does not name them.', 'result': 'week1.csv\nweek2.csv\nweek3.csv'}, {'name': 'filesystem_read_text_file', 'arguments': {'path': '/data/task_data/rosters/week1.csv'}, 'rationale': 'Read week 1.', 'result': 'shift_id,date,shift_type,staff_id,hours\n...'}, {'name': 'filesystem_read_text_file', 'arguments': {'path': '/data/task_data/rosters/week2.csv'}, 'rationale': 'Read week 2.', 'result': 'shift_id,date,shift_type,staff_id,hours\n...'}, {'name': 'filesystem_read_text_file', 'arguments': {'path': '/data/task_data/rosters/week3.csv'}, 'rationale': 'Read week 3.', 'result': 'shift_id,date,shift_type,staff_id,hours\n...'}, {'name': 'filesystem_read_text_file', 'arguments': {'path': '/data/task_data/staff.json'}, 'rationale': 'Read certifications.', 'result': '{"staff": [...]}'}, {'name': 'filesystem_create_directory', 'arguments': {'path': '/data/outputs'}, 'rationale': 'Ensure the output directory exists.', 'result': 'created'}, {'name': 'filesystem_write_file', 'arguments': {'path': '/data/outputs/report.json', 'content': '{"noncompliant_shift_ids": ["SH-1003", "SH-1006", "SH-1010", "SH-1014"], "uncertified_staff_ids": ["S-02", "S-04", "S-06"], "noncompliant_count": 4, "total_uncovered_hours": 38}'}, 'rationale': 'Write the audit report.', 'result': 'written'}]

# Channel A reads tool calls off the trajectory, so an oracle that only
# states an answer scores zero there no matter how correct the answer is.
# Replaying the reference tool sequence makes the oracle a true upper bound
# across both channels instead of only the rubric.
for i, call in enumerate(tool_calls):
    call_id = "oracle_call_%d" % i
    print(json.dumps({"type": "message", "message": {
        "role": "assistant",
        "content": call.get("rationale", ""),
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {
                "name": call["name"],
                "arguments": json.dumps(call.get("arguments", {})),
            },
        }],
    }}))
    print(json.dumps({"type": "message", "message": {
        "role": "tool",
        "tool_call_id": call_id,
        "content": call.get("result", "ok"),
    }}))

answer = "\n".join(f"- {c}" for c in claims) if claims else "No ground-truth claims for this task."
print(json.dumps({"type": "message", "message": {"role": "assistant", "content": answer}}))
print(json.dumps({"type": "result", "result": answer}))
PYEOF

echo "oracle trajectory written to /logs/agent/oracle.txt"
