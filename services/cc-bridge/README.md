# cc-bridge

OpenAI-compatible Chat Completions endpoint backed by either:

- **Subscription mode** (default): shells out to the `claude` CLI, using the
  user's Claude Code subscription auth.
- **API-key mode** (fallback): calls Anthropic directly using the `anthropic`
  Python SDK.

Point `LLM_BASE_URL=http://localhost:4000` at the mcp-atlas agent-harness and
its LiteLLM calls will route through here.

## Run

```bash
pip install -r requirements.txt
uvicorn cc_bridge:app --port 4000
# or:
python cc_bridge.py
```

## Env vars

| var                    | default                    | notes                                                                             |
| ---------------------- | -------------------------- | --------------------------------------------------------------------------------- |
| `CC_MODE`              | auto                       | `subscription` or `api_key`. Auto-detects: API-key mode iff `ANTHROPIC_API_KEY` is set and `claude` CLI is missing. |
| `ANTHROPIC_API_KEY`    | —                          | Required for `api_key` mode.                                                      |
| `CC_BRIDGE_PORT`       | `4000`                     | Port when running `python cc_bridge.py` directly.                                 |
| `CC_BRIDGE_CLAUDE_BIN` | `/opt/homebrew/bin/claude` | Path to `claude` CLI.                                                             |

## Endpoints

- `POST /v1/chat/completions` — OpenAI Chat Completions shape in and out. Requires
  a non-empty `Authorization: Bearer <anything>` header (value is not validated).
- `GET /health` — `{"status":"ok","mode":"subscription"|"api_key"}`.

## How subscription mode works

`claude -p --output-format json --model <mapped> --setting-sources "" --tools ""
--system-prompt <...> --no-session-persistence [--json-schema <router>]`

The prompt is piped in via **stdin** (not argv, to avoid ARG_MAX). System
messages are joined into `--system-prompt`. `user`, `assistant`, and `tool`
messages are concatenated into a plain-text transcript passed on stdin.

The subprocess env is scrubbed of `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`,
`CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_EXECPATH`, `AI_AGENT`, and
`CLAUDE_EFFORT`. Without this, the child CLI detects it's nested inside another
Claude Code session and exits 1 with empty stderr — invisible from the outside
because the CLI writes its actual error to stdout. On non-zero exit, the bridge
now includes both stdout and stderr in the RuntimeError.

When the request includes `tools`, we append a tools instruction to the system
prompt and pass a discriminated router schema via `--json-schema`. The CLI
returns `structured_output` with either
`{"type":"text","text":"..."}` or `{"type":"tool_call","name":"...","arguments":{...}}`,
which we translate back to OpenAI `content` or `tool_calls`.

## Model ID mapping

- `claude-opus-4.8`, `claude-opus-4-7` → `claude-opus-4-7`
- `claude-sonnet-4.5`, `claude-sonnet-4-6` → `claude-sonnet-4-6`

First substitution per alias is logged.

## Logging

Rotating file handler at `logs/cc-bridge.log` (10 MB × 5 backups) + stderr.
Each request logs mode, requested vs resolved model, tools present, latency,
and usage.

## Tests

```bash
python -m unittest discover -s tests -v
```

Smoke tests only — no live LLM calls. Covers health endpoint, model aliasing,
message translation, multimodal parsing, tool translation, and 4xx paths.

## Known limitations

- **Subscription mode ships `--tools "" --setting-sources ""`.** Without this,
  the CLI's built-in tool definitions and any auto-discovered `CLAUDE.md` /
  project settings were adding ~13k cached tokens per request. This is safe
  for a pure LLM-proxy use case but means slash-commands, MCP servers, and
  `CLAUDE.md` memory the operator has configured locally are **not** exposed
  to harness calls. This is intentional (bridge parity, not Claude Code
  parity) but flag it if the caller expects them.
- **Subscription mode uses `--system-prompt`, not `--append-system-prompt`.**
  The spec asked for append; append still layers on the ~10k-token default
  Claude Code system prompt, breaking cost/latency budgets. Overriding is a
  compromise — worth revisiting if the harness starts relying on default
  Claude Code behavior.
- **Subscription-mode tool calls are `--json-schema`-based**, not native
  Anthropic tool_use. The root-level `oneOf` shape the CLI's `--json-schema`
  claims to accept actually errors (the CLI wraps the schema into an Anthropic
  tool's `input_schema` which must be `type: object`). We flattened to
  `{type, text?, name?, arguments?}` with an enum discriminator, and validate
  the discriminator in Python after the fact.
- **Subscription-mode multimodal is best-effort.** Images and audio are
  written to temp files and referenced in the prompt as `[IMAGE attached at
  <path> media_type=...]` markers. The CLI's `--file` flag requires prior
  upload (`file_id:path`), which is not viable per-request. In practice the
  model may or may not reason usefully about the reference; for real
  multimodal use api_key mode.
- **Streaming is not implemented.** `stream: true` in the request body is
  ignored; a single JSON response is returned.
- **Rate-limit / retry behavior** is not implemented at the bridge layer.
  LiteLLM in the harness already retries on 429/401; the bridge returns
  502 on upstream failure and lets the caller decide.
- **Usage token accounting**: subscription-mode `prompt_tokens` sums input +
  cache-read + cache-creation tokens as reported by the CLI. That is a
  reasonable OpenAI-shaped proxy but not directly comparable to raw
  Anthropic billing.
