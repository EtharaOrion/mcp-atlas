# Running the rubric judge on a Codex subscription

The rubric judge grades with `gpt-5.6-sol` served by
[`CodingForMoney/codex-bridge`](https://github.com/CodingForMoney/codex-bridge),
a local server that exposes the Anthropic Messages and OpenAI Responses APIs on
top of an already-signed-in Codex login. Grading bills a ChatGPT plan rather
than API credits.

This is the same idea the bundle already uses for Claude, where `task.toml`
forwards `CLAUDE_CODE_OAUTH_TOKEN` so the verifier bills a Claude Code plan.

## Setup

```bash
npm install --global codex-anthropic-bridge   # Node 20+
codex-bridge serve                            # or: make judge-bridge
make judge-bridge-check                       # preflight
```

Codex must already be signed in: the bridge reads `~/.codex/auth.json` (or
`$CODEX_HOME/auth.json`), never writes it, and has no `login` subcommand. It
generates an API key on first use, stores it at `~/.cb/config.json`, and prints
it on `serve`. `codex_bridge.api_key()` reads that file, so it does not need to
be copied by hand. Rotating with `codex-bridge key refresh` 401s the old key
immediately.

| | |
|---|---|
| Bind | `127.0.0.1:3456` (`CODEX_BRIDGE_HOST` / `CODEX_BRIDGE_PORT`) |
| Health | `GET /health` — the only route not needing a key |
| Models | `gpt-5.6-sol` (default), `gpt-5.6-luna` — a fixed pair |
| Judge transport | `POST /v1/messages` (Anthropic Messages) |

## Two judges, two transports

There are two rubric judges in this tree and they reach their model by
different means. Wiring only one leaves the other pointed at Anthropic while
everything looks configured.

| | reaches the model via | endpoint from |
|---|---|---|
| `rubric_judge.score_rubric` | litellm | `EVAL_LLM_BASE_URL` |
| `rubric_judge_cli` | `claude_agent_sdk` -> `claude` CLI | `ANTHROPIC_BASE_URL` |

**`rubric_judge_cli` is the one that grades a real eval.** `tests/test.sh`
invokes it inside the task container. `score_rubric` is reached only by
`scripts/judge_smoke_test.py`.

`rubric_judge_cli` no longer goes through the `claude` CLI for a Codex model.
`_run_judge_direct` posts the grading prompt straight at
`POST /v1/responses`, the shape codex-bridge's upstream already speaks:

```
before:  rubric_judge_cli -> claude_agent_sdk -> `claude` CLI -> /v1/messages -> Codex
now:     rubric_judge_cli -> POST /v1/responses -> Codex
```

That removes a whole class of failure rather than just a hop. The CLI resolved
credentials from its own precedence list, so every variable outranking the one
we set had to be cleared or the bridge answered 401 on every criterion --
`CLAUDE_CODE_OAUTH_TOKEN` above all, which the shipped `task.toml` forwards into
the container and which therefore always won. The direct transport carries the
key on the request and consults no precedence at all.

It also gives up the SDK's structured-output guarantee, so the reply is parsed
with `_parse_judge_json`, which already handled bare, fenced, and prose-wrapped
JSON. An unparseable reply raises rather than returning an empty result set:
`rubric_judge_cli` writes a score file from whatever it gets back, so a judge
that quietly returned nothing would produce a rubric of zeros that reads like a
graded run.

The SDK path is removed entirely, not kept behind a flag. `_run_judge` refuses
a non-Codex model rather than reaching for another transport, and
`_OUTPUT_SCHEMA`, `_record_usage`, and `_point_sdk_at_the_bridge` are deleted
with it. The bundle's `[verifier.env]` no longer forwards
`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_*`, or `LITELLM_*` either: nothing in the
verifier reads them, and an env var that looks like judge configuration while
configuring nothing is how a run ends up pointed somewhere nobody intended.

For reference, the Anthropic Messages route the SDK used is still what
`score_rubric` takes through litellm:

```bash
ANTHROPIC_BASE_URL="http://127.0.0.1:3456" \
ANTHROPIC_AUTH_TOKEN="$CB_API_KEY" \
claude --model gpt-5.6-sol
```

`_point_sdk_at_the_bridge` sets those before grading starts, and only for a
Codex model, so asking for a Claude model still reaches Anthropic unchanged. It
also clears `ANTHROPIC_API_KEY`: the CLI prefers it, so a key inherited from the
surrounding run would be sent instead of the bridge key and every criterion
would 401.

## The one thing that is not configuration

`score_rubric` reads `EVAL_LLM_BASE_URL` and `JUDGE_MODEL` from the
environment, so pointing the judge at a backend is normally config. The
exception is the provider path.

This bridge has **no `/v1/chat/completions`**. `_call_judge_once` uses
`litellm.completion`, which for an `openai/`-prefixed model posts to
`chat/completions` — a route that does not exist here, so every criterion would
404. The Codex models therefore route through litellm's `anthropic/` provider,
which posts to `/v1/messages`. `codex_bridge.provider_route` is the single place
that decides this:

```python
gpt-5.6-sol        -> anthropic/gpt-5.6-sol
gpt-5.6-luna       -> anthropic/gpt-5.6-luna
openai/foo         -> openai/foo        # explicit provider preserved
some-other-model   -> BridgeUnavailable # refused, see below
```

Two consequences follow.

**Two base URLs.** litellm's anthropic provider appends `/v1/messages` itself,
so it takes the server root (`http://127.0.0.1:3456`) with no `/v1`. An OpenAI
Responses client takes `http://127.0.0.1:3456/v1`. Conflating them yields a 404
that reads like a model error. `check()` normalises a `/v1` root so supplying
the wrong one is not fatal.

**No `response_format`.** That is an OpenAI chat/completions parameter with no
Anthropic Messages equivalent, so it is rejected rather than ignored on this
path. `_call_judge_once` omits it for `anthropic/` models and lets
`_extract_json` recover the object from the reply, which it already does for
models that wrap JSON in prose. Strict JSON is still requested where it is
supported.

## The container cannot see 127.0.0.1

`make judge-bridge-check` uses `127.0.0.1`; the eval uses
`host.docker.internal`. That is not redundancy:

- The **preflight runs on the host**, where the bridge is on `127.0.0.1:3456`.
- The **judge runs inside the task container** — `tests/test.sh` invokes
  `/harness/scoring/rubric_judge_cli.py` — where `127.0.0.1` is the container
  and nothing is listening.

Using one value for both makes the preflight pass and every in-container call
fail. The bridge must also bind an interface the container can reach:

```bash
codex-bridge serve --host 0.0.0.0
```

The key is mandatory on every route but `/health`, so binding wider does not
expose an unauthenticated endpoint.

## What is not wired yet

`[verifier.env]` in the shipped bundles carries only `CLAUDE_CODE_OAUTH_TOKEN`:

```toml
[verifier.env]
CLAUDE_CODE_OAUTH_TOKEN = "${CLAUDE_CODE_OAUTH_TOKEN}"
```

`EVAL_LLM_BASE_URL`, `EVAL_LLM_API_KEY`, and `JUDGE_MODEL` are not forwarded, so
setting them on the host does **not** reach the in-container judge; it falls
back to `_DEFAULT_BASE_URL`, which inside the container resolves to the
container. `adapters/mcp_atlas/adapter.py` now emits all three, so **newly
generated** bundles carry them. The two bundles already in `dataset/` predate
that and need regenerating or patching.

That is a deliberate stopping point. `dataset/` bundle bytes are digested into
`task_artifact_hashes` in `memory/crucible_view.yaml` under
`bytes_moved_since_canary_issue: false`. Editing a shipped `task.toml` changes
`task_hash` and breaks that canary binding, which is an audit decision rather
than a wiring one.

## Caveats that belong in any run record

- **The judge is not pinned.** Upstream describes the ChatGPT-authenticated
  Codex backend as "not a documented stable third-party API".
  `codex_bridge.BridgeStatus.as_record()` emits `backend_pinned: false` with the
  resolved model and transport so a run states this rather than implying a
  pinned judge.
- **Judge failures are counted, not raised.** `score_rubric` catches
  per-criterion errors and still returns a reward, so a stopped or
  unauthenticated bridge produces a complete-looking report computed from almost
  nothing. That is why `preflight()` exists and why `run-eval-codex` depends on
  `judge-bridge-check`.
- **Volume.** The discipline is 11 trials per criterion (`_JUDGE_TRIALS = 11`).
  Criteria x trials x tasks is a lot of subscription calls.
- **Token counts are estimates.** The bridge describes `count_tokens` as "a
  conservative compatibility estimate", not suitable for billing.
