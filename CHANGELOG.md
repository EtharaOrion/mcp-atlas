# Changelog

## Unreleased — Harbor adapter repair

The MCP-Atlas -> Harbor adapter emitted bundles that could never run. All of
it was invisible because `adapters/` had no tests and CI only covered the
agent-environment pin-sync suite.

### Fixed

- **Bundles declared no MCP servers.** `adapters/mcp_atlas/adapter.py` wrote a
  `task.toml` with no `[[environment.mcp_servers]]` block at all, so a Harbor
  agent ran an MCP tool-use benchmark with zero tools.
- **The per-task tool allowlist was dropped.** `MCPAtlasRecord.enabled_tools`
  was parsed off the dataset row (and `--tool-map` was a documented flag) but
  `generate_task()` never wrote it anywhere. Every task got the sandbox's full
  307-tool surface instead of the tools it was scoped to. Now written to
  `environment/enabled_tools.txt`, `COPY`d into the image, and enforced by the
  bridge on both `tools/list` and `tools/call`.
- **The compose file had no `main` service.** Harbor runs the agent in the
  service named `main` (`harbor.constants.MAIN_SERVICE_NAME`) and collects
  artifacts from it; the old single-service compose brought up a sidecar and
  no agent.
- **The agent timeout was silently discarded.** The adapter wrote the Harbor
  1.0 key `[agent] timeout`; on Harbor 0.20 (schema 1.3) that key is dropped
  during migration, leaving `[agent]` empty and falling back to the default
  timeout. Bundles now target schema 1.3 natively and write `timeout_sec`.
- **The healthcheck passed against a dead sandbox.** The image's `/health`
  returns HTTP 200 even when the MCP client is down, encoding failure in the
  body, so `curl -sf` always succeeded. The check now matches on
  `health_and_client_connection_ok`.
- **The oracle could not pass.** `solution/solve.sh` was `echo "no solution"`,
  which left `/logs/agent/` empty; `tests/agent_judge.py` then raised
  "No trajectory .txt files found" and scored 0. The oracle now writes the
  ground-truth claims as a judge-readable trajectory, so the oracle gate
  measures the verifier instead of failing by construction.
- **Registry metadata and network policy were absent.** `[task].name`,
  `description` and `keywords` are populated (an empty description blocks
  `harbor publish`), and `network_mode` is explicit.
- Fixed 5 failing tests in `services/scoring/tests/test_score_weighted.py`:
  `asyncio.Semaphore()` was constructed outside a running loop, which raises
  on Python <= 3.9.

### Added

- `adapters/mcp_atlas/mcp_rest_bridge.py` — a stdio MCP server that fronts the
  sandbox's REST API. The mcp-atlas image speaks a bespoke REST API on :1984
  and no MCP protocol at all, which is why bundles pointing at
  `http://localhost:18765/mcp` never passed a healthcheck. The bridge runs in
  the agent's own container and proxies `tools/list` and `tools/call`,
  enforcing the task's allowlist.
- `adapters/mcp_atlas/tests/test_adapter.py` — 20 structural regression tests,
  one per defect above. No Docker, no network.
- `scripts/smoke_test.py` (`make smoke`) — end-to-end: generate a bundle from a
  real dataset row, validate it against Harbor's own task model, confirm
  Harbor round-trips it without rewriting, drive a full MCP handshake through
  the bridge against a stub sandbox, and run the oracle through the verifier's
  own extraction logic.
- `.github/workflows/python-tests.yml` — runs the unit suites on Python 3.9 and
  3.12 plus the smoke test. Previously none of this ran in CI.
- `make test` now runs every suite (`test-env` + `test-python`).
- `run_adapter.py` gained `--org`, `--network-mode` and `--sandbox-port`.

### Added — task data and output capture

- Tasks can now carry input files. A manifest row with `DATA_DIR` (resolved
  against the manifest, not the cwd) copies that directory into the bundle and
  mounts it read-only at `/data/task_data` on the **mcp-server sidecar**. The
  MCP servers run in the sidecar, not the agent's container, and both the
  filesystem server (rooted at `/data`) and desktop-commander (`allowedDirectories
  = ["/data"]`) are blind to anything outside `/data` -- mounting elsewhere
  would put the data where no tool can read it.
- Generated bundles now declare `[[artifacts]]` collecting `/data/outputs` with
  `service = "mcp-server"`, so files the agent writes are retrieved from the
  container they actually land in.
- `examples/tasks/vendor-audit/` -- a runnable sample task exercising both:
  keyless tools, authored data, exact ground truth, and an oracle that scores
  1.0.

### Deprecated

- `services/mcp_eval/convert_tasks_to_harbor.py` as a bundle generator for
  MCP-Atlas. It targets a generic image that already serves MCP over
  streamable-http and emits the Harbor 1.0 schema; against an mcp-atlas image
  its bundles cannot pass a healthcheck. It now warns loudly when pointed at
  one. It is retained because it owns the shared templates the adapter imports.
  `adapters/mcp_atlas/adapter.py` is the canonical generator.

### Known gaps (not addressed here)

- The bundles under `output/harbor/` were rendered by the deprecated converter
  and are stale. They were left in place because they carry real run output.
- The runtime still cannot express multimodal tasks, mount task data, run a
  task more than once (no pass@k), or capture files the agent wrote.

## v2.0.0 — Agent harness migration to TypeScript

### What changed

The agent harness has been rewritten from Python to TypeScript. The previous
Python harness (`services/mcp_eval/mcp_completion/`) is removed and replaced by
a TypeScript implementation under `services/agent-harness/`.

Scoring (`services/scoring/`) and the new diagnostic pipeline
(`services/diagnostics/`) remain in Python.

### Why TypeScript

- **Pluggable provider strategies.** Each model provider lives in a single
  strategy file under `agent-evals/strategies/`. The included LiteLLM strategy
  works with any model reachable via a LiteLLM-compatible proxy (OpenAI,
  Anthropic, Gemini, self-hosted endpoints, etc.). Adding a new provider is a
  single-file change.
- **Better concurrency for parallel task evaluation.** Node's event loop lets
  one harness instance run many tasks against the sandbox concurrently
  without thread/process orchestration overhead.
- **Hot reload during development.** `npm run dev` picks up source changes
  automatically — useful when iterating on a strategy.
- **Per-strategy retry policy.** The LiteLLM strategy handles 429 / 401 / 5xx
  backoff appropriately, including LiteLLM proxy token-cache delays.

### Scaling beyond local docker

By default the TypeScript harness talks to a local docker container running
`ghcr.io/scaleapi/mcp-atlas`, accessed via the `MCP_SANDBOX_URL` env var
(default `http://localhost:1984`). A single sandbox is fine for development
and smaller evaluations.

For large-scale runs (many tasks in parallel, each on its own sandbox), the
harness can be combined with a **sandbox orchestrator** that creates an
ephemeral sandbox per task and exposes its URL via `MCP_SANDBOX_URL`. Any
orchestrator that returns an HTTP endpoint implementing the agent-environment
API will work — the harness needs no changes. Scale's internal eval
infrastructure uses a Modal-based proxy for this; that proxy is not included
in this release, but the public harness is designed to plug into one.

### New: top-level batch runner

- `run_eval.py` — drives the agent harness over the full dataset and writes a
  CSV in the format the scoring step expects (`task_id`,
  `raw_conversation_history`, `response`). Defaults to loading from HuggingFace
  (`ScaleAI/MCP-Atlas`, 500 tasks). Supports concurrent task execution and
  resumes safely if interrupted. See `make install-python` and
  `python run_eval.py --help`.

### New: scoring and diagnostic pipelines

- `services/scoring/score_claims.py` — LLM-as-judge coverage scoring with
  configurable evaluator model (default: `gemini/gemini-3.1-pro-preview`).
  Reports `pass_rate_0.75` and `mean_coverage` per split.
- `services/scoring/analyze_errors.py` — error distribution summary across
  completion runs.
- `services/diagnostics/single_model_diagnostic.py` — the headline addition:
  scoring tells you *that* a model failed; diagnostics tell you *how*. For every
  below-threshold task, an LLM judge reads an **enriched trajectory** (turn-by-turn
  tool calls, parameters, status, errors, and output summaries — not the raw
  transcript) and classifies the failure into one of **11 modes**:
  - **4 tool-call modes** — `malformed_call`, `wrong_tool`, `no_tool_use`,
    `err_recovery`.
  - **7 cognitive modes** — `task_misunderstanding`, `faulty_synthesis`,
    `response_misparsing`, `early_termination`, `hallucinated_fact`,
    `logical_error`, `constraint_violation`.

  Each task gets a primary failure plus any contributing failures (each with a
  root-cause flag), a calibrated confidence, and a scorer-grounded explanation.
  These roll up to a model-level tool-call-vs-cognitive split, a full
  failure-mode distribution, public-split examples per mode, and an
  LLM-generated narrative. Runs with no model-attributable failure (infra
  errors, empty output) are labelled `analysis_error` and excluded from the
  reported stats. The taxonomy in `mcp_failure_taxonomy.py` is the single
  source of truth for both diagnosis and reporting.
- `services/diagnostics/extract_enriched_trajectory.py` — builds the enriched
  trajectory (from the raw conversation history) that the diagnostic reads;
  also backfills it onto existing scored CSVs.

### Verification helpers

- `services/mcp_eval/test_servers.py` — health-check across every MCP server
  defined in `mcp_server_template.json`. Makes one representative call per
  server, reports pass/fail, and explicitly flags any API keys missing from
  `.env`. Run after adding keys to confirm everything works:
  ```bash
  python test_servers.py
  ```

### Provider strategy

- **LiteLLM** (`agent-evals/strategies/litellm-strategy.ts`) — generic OpenAI
  Chat Completions API client. Configure with `LLM_API_KEY` and
  `LLM_BASE_URL`. Comma-separated keys are rotated per-request.

To add a new provider, implement the `AgentCompletionStrategy` interface in
a new file under `agent-evals/strategies/` and dispatch to it from
`agent-evals/completion-strategy.ts`. Use `litellm-strategy.ts` as a
reference.

### Removed

- `services/mcp_eval/mcp_completion/` (the entire Python harness)
- `services/mcp_eval/mcp_completion_script.py`
- `services/mcp_eval/mcp_evals_scores.py` (replaced by `services/scoring/score_claims.py`)
- `services/mcp_eval/run.py` (a replacement public run script will land in a
  follow-up release)
- The `run-mcp-completion` Makefile target

### Environment variables

| Variable | Used by | Notes |
|----------|---------|-------|
| `LLM_API_KEY` | agent-harness | Required. Comma-separated keys are rotated. |
| `LLM_BASE_URL` | agent-harness | Required. URL of an OpenAI-compatible (or LiteLLM proxy) endpoint. |
| `MCP_SANDBOX_URL` | agent-harness | Default `http://localhost:1984`. Points at the running `agent-environment` container. |
| `EVAL_LLM_API_KEY` | scoring, diagnostics | Falls back to `LLM_API_KEY`. |
| `EVAL_LLM_BASE_URL` | scoring, diagnostics | Falls back to `LLM_BASE_URL`. |
| `EVAL_LLM_MODEL` | scoring, diagnostics | Default judge model. |
