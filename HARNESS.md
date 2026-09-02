# HARNESS

MCP-Atlas is a multi-turn LLM agent benchmark built around real-world software workflows. Agents complete tasks by calling tools exposed via the Model Context Protocol (MCP) against a fleet of mock SaaS applications.

## Repository layout

```
harness/
├── adapters/mcp_atlas/       HuggingFace dataset -> Harbor task bundle converter
├── input/                    MCP-Atlas.parquet dataset
├── output/                   Per-task run artifacts (summary, trajectory, verifier results)
├── run_eval.py               Async batch runner for HuggingFace eval
├── scripts/
│   ├── run_task.sh           Run a single task bundle via Harbor
│   ├── run_batch.py          Resumable multi-task batch runner
│   ├── harbor_to_output.py   Reshape a Harbor job into output/<task>/
│   ├── finance_reporter.py   POST token/cost usage to Finance API
│   └── smoke_test.py         End-to-end bundle generation validation
├── services/
│   ├── agent-environment/    Docker image with 36 MCP tool servers (port 1984)
│   ├── agent-harness/        TypeScript multi-turn agent loop (port 3001)
│   ├── cc-bridge/            Claude Code bridge - OpenAI-compatible proxy (port 4000)
│   ├── diagnostics/          11-mode failure classifier
│   ├── light-servers/        Mock SaaS application fleet (140 domain + 20 tool servers)
│   ├── mcp_eval/             Health tests and eval utilities
│   └── scoring/              LLM-as-judge and score aggregation pipeline
└── tasks/                    Harbor-format task bundles
```

## Quick start

### Prerequisites

- Docker (BuildKit enabled)
- Node.js 18+, Python 3.11+, uv

### 1. Build images

```bash
make build               # agent-environment (36 MCP tool servers, port 1984)
make build-light-servers # mock SaaS fleet (ports 8000-8090, 9000-9144)
```

### 2. Run the agent-environment

```bash
make run-docker          # starts agent-environment on port 1984
```

### 3. Run the agent harness

```bash
make install-harness     # npm install in services/agent-harness
make run-harness         # TypeScript harness on port 3001
```

### 4. Run a single task

```bash
make run-task TASK=tasks/arlingham-parcel-loss-audit
# with options:
make run-task TASK=tasks/arlingham-parcel-loss-audit MODEL=claude-opus-4-7 AGENT=claude-code N=3
```

Output lands in `output/<task-name>/`.

### 5. Run the full HuggingFace eval

```bash
make run-eval MODEL=claude-opus-4-7 OUTPUT=output/
```

## Running a task bundle

```bash
bash scripts/run_task.sh tasks/<task-dir>
```

Key environment variables:

| Variable | Effect |
|---|---|
| `MODEL` | LLM model name passed to the harness |
| `AGENT` | Agent adapter (e.g. `claude-code`) |
| `N` | Number of trials (default 1) |
| `LLM_BASE_URL` | Override LLM endpoint (e.g. `http://localhost:4000` for cc-bridge) |
| `ANTHROPIC_API_KEY` | API key for agent and judge |
| `SKIP_IMAGE_REFRESH` | Set to `1` to skip Docker image rebuilds |
| `BUILD_MULT` | Multiply healthcheck start_period (useful when starting all 161 servers) |

Output directory structure:

```
output/<task>/
├── summary.json           Aggregated metrics across all trials
├── pass_summary.json      Pass rate and score breakdown
├── passk_summary.json     Pass@k statistics
├── report.md              Human-readable run report
└── trajectory/
    └── Run_N/
        ├── agent/         Agent turn-by-turn trace
        ├── verifier/      Grading artifacts
        │   ├── state_channel.json
        │   ├── reward_channel_a.json
        │   ├── rubric_breakdown.json
        │   └── ctrf.json
        └── logs/
```

## Task bundle format

See `TASK_BUNDLE.md` for the full reference. Summary:

```
<task>/
├── task.toml            Manifest: identity, timeouts, MCP servers, resource caps
├── instruction.md       Agent prompt (verbatim)
├── data/                Read-only attachments (images, PDFs, etc.)
├── environment/
│   ├── Dockerfile
│   └── docker-compose.yaml
├── tests/
│   ├── test.sh          Verifier entrypoint
│   ├── test_outputs.py  Scored pytest suite (Channel A)
│   ├── test_weights.json  Grading ledger: component weights + per-test weights
│   ├── rubric.json      LLM judge criteria (Channel B)
│   ├── gt_env.json      Ground-truth world state after a correct run
│   ├── oracle.json      Minimal write set a correct agent performs
│   └── state_dump.py    Captures post-run world state
└── solution/            Reference answer (not executed in grading)
```

### Scoring formula

```
reward = max(0, (W_A * chanA + W_B * rubric + W_C * Rc - W_M * Rb) / basis)
```

| Component | Typical weight | Description |
|---|---|---|
| `chanA` (traj_tests) | 5 | Pytest trajectory assertions: `max(0, (earned - penalty) / pos_total)` |
| `rubric` | 3 | LLM judge: satisfied positive criteria / total positive criteria weight |
| `Rc` (state_completion) | 5 | World state match: 1.0 if end_env matches gt_env exactly, else 0.0 |
| `Rb` (state_misbehave) | -5 | Collateral damage: fraction of non-target entities drifted |

Weights and `threshold` are defined per task in `tests/test_weights.json`.

Gates (set in test_weights.json):
- `require_no_guards: true` - any guard test passing (agent misbehaved) zeroes Channel A
- `require_state_exact: false` - state channel participation is optional per task

## Light-servers

Mock SaaS applications the agent calls via MCP. Two categories:

### Tool servers (ports 8000-8090)

Located in `services/light-servers/servers/`. Pure functional - no session state, no auth. 20 servers:

| Ports | Servers |
|---|---|
| 8000-8007 | math, unit, osint, time, lang, crypto, graphs, chem |
| 8013-8024 | url, csv_server, json_server, diff, hash, color, encoding, barcode, calendar_math, currency, random_server, template |
| 8090 | filesystem (list_directory, read/write files, create_directory) |

Note: `unit` server launches via `python3 -m servers.unit.app`, not `fastmcp run`.

### Software (domain) servers (ports 9000-9144)

Located in `services/light-servers/software/Light*/`. 140 mock SaaS apps with full CRUD operations.

All follow a 3-layer architecture:

```
app.py        FastMCP tool definitions
session.py    Session registry (session_dict: Dict[str, <App>Session])
<app>.py      Business logic class - holds state, implements domain methods
```

Every tool follows this pattern:

```python
@mcp.tool
async def create_thing(params, session_id: str):
    session, err = get_session(session_id)
    if err:
        return err
    return session.<app>_session.create_thing(params)
```

Standard response envelope: `{"status": "ok", "output": <data>}` or `{"status": "failed", "output": <message>}`.

**LightSystem** (port 9000) is the OS master. All other apps call it for `now`, `health`, and session management. Agents log in to LightSystem first; its `session_id` is passed to other apps via `os_cfg`.

**World initialization:**
- Seedless (production): state restored from `software/Light*/world.pkl` snapshot (deterministic)
- Seeded (development): state built from `corpus/<app>.yaml` via `COMPLEXMCP_SEED` env var

**Selecting servers:** Set `ENABLED_SERVERS` in the task's `docker-compose.yaml` environment block. Without it, all 161 servers start simultaneously (slow, 12+ min). Example:

```yaml
environment:
  ENABLED_SERVERS: "LightStripe,LightZendesk,LightSlack"
```

Port map:
- 9000: LightSystem
- 9001-9043: first-wave domain apps
- 9044-9144: second-wave domain apps

## Scoring pipeline

1. Agent runs, writing to live light-servers
2. Verifier runs `test.sh`, which:
   - Calls `state_dump.py` to capture `end_env.json`
   - Runs `test_outputs.py` (pytest) for trajectory assertions and state diff - writes `reward_channel_a.json` and `state_channel.json`
   - Runs the rubric judge against `rubric.json` - writes `rubric_breakdown.json`
3. `scripts/harbor_to_output.py` reshapes the Harbor job into `output/<task>/`

Key verifier output files:

| File | Contents |
|---|---|
| `state_channel.json` | `{completion, misbehave, missing, unexpected, changed}` |
| `reward_channel_a.json` | `{reward, channel_a, rubric, ledger, missed, guards_tripped}` |
| `rubric_breakdown.json` | Per-criterion scores from LLM judge |
| `ctrf.json` | Per-test results with weights (CTRF format) + `final_reward` |

## CC-bridge

`services/cc-bridge/cc_bridge.py` is an OpenAI-compatible proxy that routes LLM calls through the Claude Code CLI instead of the Anthropic API. Use it to run agents on Claude without a direct API key when a Claude Code subscription is active.

```bash
cd services/cc-bridge
python cc_bridge.py        # starts on port 4000
curl http://localhost:4000/health
# {"status": "ok", "mode": "subscription"}
```

To route an agent run through the bridge:

```bash
LLM_BASE_URL=http://localhost:4000 bash scripts/run_task.sh tasks/<task>
```

Supported model aliases:

| Alias | Maps to |
|---|---|
| `claude-opus-4.8` | `claude-opus-4-7` |
| `claude-sonnet-4.5` | `claude-sonnet-4-6` |

Limitation: In subscription mode, images are written to temp files and referenced as `[IMAGE attached at <path>]` markers rather than native multimodal content. Use api_key mode for full multimodal support.

## Development commands

| Command | Effect |
|---|---|
| `make build` | Build agent-environment Docker image |
| `make build-light-servers` | Build light-servers Docker image |
| `make run-docker` | Run agent-environment on port 1984 |
| `make run-harness` | Start TypeScript harness on port 3001 |
| `make test` | Run all test suites (test-env + test-python) |
| `make test-python` | Adapter + scoring + unit tests (no Docker required) |
| `make smoke` | End-to-end bundle generation + Harbor validation |
| `make run-task TASK=tasks/<dir>` | Run a single task bundle |
| `make run-batch ALL=1` | Run all tasks as a resumable batch |
| `make batch-status` | Print batch progress without running |
| `make harbor-output JOB=jobs/<job>` | Reshape existing Harbor job into output/ |
| `make finance-usage RUN=output/<task>/trajectory/Run_1` | Post token/cost to Finance API |
| `make push` | Build and push multi-arch image to ghcr.io/scaleapi/mcp-atlas |
