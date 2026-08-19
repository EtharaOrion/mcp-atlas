# /// script
# dependencies = [
#   "pytest>=7.0",
# ]
# ///

"""Weighted judge entry point for --weighted Harbor bundles.

Combines Channel A (tests/test_outputs.py + tests/test_weights.json, via the
tests/traj_asserts.py + tests/weighted_judge.py copies sitting next to this
file) with Channel B (the rubric score agent_judge.py already computed, read
back from the rubric_breakdown.json it wrote to /logs/verifier/). Only
overwrites reward.json/reward.txt when at least one component is actually
opted in (non-zero weight) — otherwise agent_judge.py's own reward.json is
left exactly as it wrote it, so a --weighted bundle with an untouched
test_weights.json scores identically to a plain bundle.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/tests")
import weighted_judge as wj  # noqa: E402


def find_agent_trajectory_filepath(agent_dir: Path = Path("/logs/agent")) -> str:
    if not agent_dir.exists():
        raise RuntimeError(f"{agent_dir}/ directory not found")
    txt_files = [f for f in agent_dir.iterdir() if f.is_file() and f.suffix == ".txt"]
    if not txt_files:
        raise RuntimeError(f"No trajectory .txt files found in {agent_dir}/")
    return str(max(txt_files, key=lambda f: f.stat().st_size))


def load_flat_messages_and_response(trajectory_path: str):
    """Parse the {"type": "message"/"result", ...} line-JSON trajectory file
    (the same shape agent_judge.py's own find_agent_trajectory_filepath() /
    extract_agent_response() read) into (flat OpenAI-message list, final
    response) — traj_asserts.py accepts the flat-message-list shape directly."""
    messages = []
    response = ""
    for line in Path(trajectory_path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if event.get("type") == "message" and event.get("message"):
            messages.append(event["message"])
        elif event.get("type") == "result" and event.get("result"):
            response = event["result"]
    return messages, response


def main(
    agent_dir: Path = Path("/logs/agent"),
    out_dir: Path = Path("/logs/verifier"),
    tests_dir: Path = Path("/tests"),
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        trajectory_path = find_agent_trajectory_filepath(agent_dir)
        messages, _response = load_flat_messages_and_response(trajectory_path)

        weights_file = tests_dir / "test_weights.json"
        test_file = tests_dir / "test_outputs.py"
        weights = wj.load_weights(weights_file)

        traj_results = None
        if weights.traj_tests.weight and test_file.exists():
            traj_results = wj._run_traj_pytest(messages, test_file)

        rubric_value = None
        rubric_rows = []
        breakdown_path = out_dir / "rubric_breakdown.json"
        rubric_file = tests_dir / "rubric.json"
        if weights.rubric.weight and breakdown_path.exists():
            breakdown = json.loads(breakdown_path.read_text())
            per_criterion = breakdown.get("results", [])
            if rubric_file.exists() and per_criterion:
                # Weighted Channel B: agent_judge.py already judged every
                # criterion, so reuse its per-criterion verdicts and apply
                # this task's own weights and polarity. No extra LLM calls.
                # Without a rubric.json we fall back to agent_judge.py's
                # all_pass aggregate, which is all-or-nothing across every
                # criterion.
                import rubric_weighted as rw

                criteria = rw.parse_rubric(json.loads(rubric_file.read_text()))
                by_id = {str(r.get("id")): r for r in per_criterion}
                verdicts = [by_id.get(c.id, {"score": 0.0}) for c in criteria]
                scored = rw.score_verdicts(criteria, verdicts)
                rubric_value = scored["value"]
                rubric_rows = scored["rows"]
            else:
                rubric_value = breakdown.get("score")
                rubric_rows = per_criterion

        result = wj.judge_weighted(
            test_weights_file=weights_file,
            traj_results=traj_results,
            rubric_value=rubric_value,
            rubric_weight=weights.rubric.weight,
            rubric_rows=rubric_rows,
        )

        if result["reward"] is None:
            print("No weighted-grading component active for this task "
                  "(test_weights.json inert) -- leaving agent_judge.py's "
                  "reward.json unchanged.")
            (out_dir / "detail.json").write_text(json.dumps(result, indent=2))
            return

        wj.write_verifier_artifacts(out_dir, result)
        print(f"Weighted reward: {result['reward']}")

    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(f"weighted_judge_entry.py failed ({e}); leaving reward.json "
              f"as agent_judge.py wrote it.", file=sys.stderr)


if __name__ == "__main__":
    main()
