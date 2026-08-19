# /// script
# dependencies = [
#   "claude-agent-sdk>=0.1.45",
# ]
# ///

"""Agent judge for rubrics verification."""

import asyncio
import json
import os
import sys
from pathlib import Path
from string import Template

_api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
_base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip()
if _api_key:
    os.environ["ANTHROPIC_AUTH_TOKEN"] = _api_key
if not _base_url:
    os.environ.pop("ANTHROPIC_BASE_URL", None)

CRITERIA = [{'id': 'claim_1', 'title': 'The latest study related to oncology and machine learning published in November 2024 containing the word "cancer" in its title was "xCG: Explainable Cell Graphs for Survival Prediction in Non-Small Cell Lung Cancer"'}, {'id': 'claim_2', 'title': 'The title of the article "xCG: Explainable Cell Graphs for Survival Prediction in Non-Small Cell Lung Cancer" translates into Spanish as "xCG: gráficos de celdas explicables para la predicción de supervivencia en el cáncer de pulmón de células no pequeñas".'}, {'id': 'claim_3', 'title': 'The abstract of the article is: "Understanding how deep learning models predict oncology patient risk can\nprovide critical insights into disease progression, support clinical\ndecision-making, and pave the way for trustworthy and data-driven precision\nmedicine. Building on recent advances in the spatial modeling of the tumor\nmicroenvironment using graph neural networks, we present an explainable cell\ngraph (xCG) approach for survival prediction. We validate our model on a public\ncohort of imaging mass cytometry (IMC) data for 416 cases of lung\nadenocarcinoma. We explain survival predictions in terms of known phenotypes on\nthe cell level by computing risk attributions over cell graphs, for which we\npropose an efficient grid-based layer-wise relevance propagation (LRP) method.\nOur ablation studies highlight the importance of incorporating the cancer stage\nand model ensembling to improve the quality of risk estimates. Our xCG method,\ntogether with the IMC data, is made publicly available to support further\nresearch."'}, {'id': 'claim_4', 'title': 'In 1912, Isaac Adler published the first literature review about lung cancer'}]

AGENT_PROMPT = 'For a report I have to prepare on oncology with machine learning, help me identify the last related study published on november 2024 containing the word cancer in its title and retrieve the abstract of the article. Translate only the title of the study into spanish while keeping the abstract of the study in its original language. Find the type of cancer discussed in the article and tell me who published the first literature and in which year.'

SCORE_AGGREGATOR = "all_pass"

OUTPUT_SCHEMA = {
  "type": "json_schema",
  "schema": {
    "type": "object",
    "properties": {
      "results": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "id": {"type": "string"},
            "score": {"type": "number"},
            "justification": {"type": "string"}
          },
          "required": ["id", "score", "justification"]
        }
      }
    },
    "required": ["results"]
  }
}


def find_agent_trajectory_filepath():
    agent_dir = Path("/logs/agent")
    if not agent_dir.exists():
        # Raise (not sys.exit) so __main__'s `except Exception` writes a
        # reward.json; SystemExit is a BaseException and would bypass it.
        raise RuntimeError("/logs/agent/ directory not found")
    txt_files = [f for f in agent_dir.iterdir() if f.is_file() and f.suffix == ".txt"]
    if not txt_files:
        raise RuntimeError("No trajectory .txt files found in /logs/agent/")
    return str(max(txt_files, key=lambda f: f.stat().st_size))


def extract_agent_response(trajectory_path):
    agent_response = ""
    for line in Path(trajectory_path).read_text().splitlines():
        try:
            event = json.loads(line)
            if event.get("type") == "result" and event.get("result"):
                agent_response = event["result"]
        except (json.JSONDecodeError, TypeError):
            pass
    return agent_response


EVALUATION_PROMPT_TEMPLATE = Template(
    "An agent was given the following prompt and generated the trajectory and response below. "
    "Analyze the agent's trajectory and response against the following criteria.\n\n"
    "## Agent Prompt\n<agent_prompt>\n$agent_prompt\n</agent_prompt>\n\n"
    "## Agent Trajectory\nThe agent's trajectory is available at $trajectory_path\n\n"
    "## Agent Response\n<agent_response>\n$agent_response\n</agent_response>\n\n"
    "## Criteria\n$criteria_json\n\n"
    "## Instructions\nFor each criterion, determine whether the agent's behavior PASSES or FAILS.\n\n"
    "For each criterion, return a result with:\n"
    "- \"id\": the criterion's id\n"
    "- \"score\": 1.0 if the criterion is met, 0.0 if it is not\n"
    "- \"justification\": a brief explanation of why you chose this score"
)


def aggregate_score(results):
    if SCORE_AGGREGATOR == "all_pass":
        # An incomplete judge result set (fewer rows than criteria) must fail:
        # missing criteria are treated as failures, not silently passed over.
        if not results or len(results) != len(CRITERIA):
            return 0.0
        return 1.0 if all(r.get("score") == 1.0 for r in results) else 0.0
    raise ValueError(f"Unknown aggregator: {SCORE_AGGREGATOR}")


def extract_result(messages):
    for msg in reversed(messages):
        if hasattr(msg, "structured_output") and msg.structured_output is not None:
            return msg.structured_output if isinstance(msg.structured_output, str) else json.dumps(msg.structured_output)
        if hasattr(msg, "result") and msg.result:
            return msg.result
    return ""


async def run_judge():
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    model = os.getenv("JUDGE_MODEL", "claude-sonnet-4-6")
    trajectory_path = find_agent_trajectory_filepath()
    print(f"Found trajectory: {trajectory_path} ({Path(trajectory_path).stat().st_size} bytes)")
    agent_response = extract_agent_response(trajectory_path)
    eval_prompt = EVALUATION_PROMPT_TEMPLATE.substitute(
        agent_prompt=AGENT_PROMPT,
        agent_response=agent_response,
        criteria_json=json.dumps(CRITERIA, indent=2),
        trajectory_path=trajectory_path,
    )

    print(f"Running judge agent: {model} (effort=low)")
    print(f"Criteria count: {len(CRITERIA)}")

    options = ClaudeAgentOptions(
        allowed_tools=["Bash", "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "TodoWrite", "Task", "ExitPlanMode"],
        permission_mode="acceptEdits",
        model=model,
        max_turns=120,
        output_format=OUTPUT_SCHEMA,
        effort="low",
    )

    messages = []
    async with ClaudeSDKClient(options) as client:
        await client.query(prompt=eval_prompt)
        async for message in client.receive_response():
            messages.append(message)

    print(f"Judge agent finished. Total messages: {len(messages)}")

    result_text = extract_result(messages)
    if not result_text:
        raise RuntimeError("Judge agent produced no result")

    text = result_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    parsed = json.loads(text)
    results = parsed.get("results", []) if isinstance(parsed, dict) else parsed

    if len(results) != len(CRITERIA):
        print(f"WARNING: Judge returned {len(results)} results but expected {len(CRITERIA)}", file=sys.stderr)

    agg_score = aggregate_score(results)

    criteria_by_id = {c["id"]: c for c in CRITERIA}
    verified_results = []
    for r in results:
        criterion = criteria_by_id.get(r.get("id"), {})
        verified_results.append({
            **criterion,
            "score": r.get("score", 0.0),
            "result": r.get("score") == 1.0,
            "justification": r.get("justification", ""),
        })

    Path("/logs/verifier").mkdir(parents=True, exist_ok=True)
    # Harbor parses reward.json into VerifierResult(rewards: dict[str, float | int]);
    # it must be a flat scalar dict keyed by Harbor's default "reward" key.
    Path("/logs/verifier/reward.txt").write_text(str(agg_score))
    Path("/logs/verifier/reward.json").write_text(json.dumps({"reward": agg_score}, indent=2))
    # Preserve the full rubric breakdown for analysis/debugging (not read by Harbor).
    Path("/logs/verifier/rubric_breakdown.json").write_text(
        json.dumps({"score": agg_score, "results": verified_results}, indent=2)
    )

    print(f"\nResults:")
    for r in results:
        status = "PASS" if r.get("score") == 1.0 else "FAIL"
        print(f"  [{status}] {r.get('id', '?')[:8]}: {r.get('justification', '')[:100]}")
    print(f"\nAggregate score: {agg_score}")


if __name__ == "__main__":
    try:
        asyncio.run(run_judge())
    except Exception as e:
        import traceback
        print(f"Judge failed: {e}", file=sys.stderr)
        traceback.print_exc()
        Path("/logs/verifier").mkdir(parents=True, exist_ok=True)
        Path("/logs/verifier/reward.txt").write_text("0.0")
        Path("/logs/verifier/reward.json").write_text(json.dumps({"reward": 0.0}, indent=2))
        Path("/logs/verifier/rubric_breakdown.json").write_text(json.dumps({
            "score": 0.0,
            "error": str(e),
            "results": [],
        }, indent=2))
