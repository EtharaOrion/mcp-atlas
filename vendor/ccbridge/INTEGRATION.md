# ccbridge — Claude Code OAuth proxy (vendored)

Vendored verbatim from `mcp-stump/vendor/ccbridge/` (package `claude_oauth`).
Every claim below is drawn from the source files in this directory; nothing here
is invented. Where the upstream code names paths from its origin project
(`src.utils.claude_oauth`, `run_pipeline.sh`, `openclaw`, `wildclawbench`), those
are the original author's references, not complex-mcp paths.

## (a) What this is and why it's vendored

`ccbridge` is a small FastAPI HTTP proxy that lets a caller drive the Anthropic
Messages API through a **Claude Code OAuth subscription** (a Max/Pro plan) instead
of a raw `ANTHROPIC_API_KEY`. Per `claude_oauth/__init__.py` and `bridge.py`, it:

1. Reads Claude Code OAuth credentials from the system store (macOS Keychain,
   `~/.claude/.credentials.json`, or env/file overrides) — see `credentials.py`.
2. Exposes an Anthropic-compatible server that forwards each request upstream to
   `https://api.anthropic.com` with the OAuth **bearer token** (replacing the
   incoming `x-api-key`), the required `anthropic-beta: oauth-2025-04-20` header,
   and — on `POST /v1/messages` — the mandatory
   `"You are Claude Code, Anthropic's official CLI for Claude."` system prefix
   that Anthropic requires on OAuth-scoped messages.

It is vendored so containerised trials can spend a Claude Code subscription
rather than metered API-key credits. It refreshes the OAuth token automatically
(`credentials.py::refresh_credentials`, endpoint
`https://console.anthropic.com/v1/oauth/token`), classifies upstream errors
(`errors.py`), and transparently retries/failovers on throttles, 5xx, and
subscription-cap 429s (`bridge.py`, `recovery.py`).

### File inventory (`claude_oauth/`)

- `__init__.py` — package exports (credential providers, error classifier).
- `__main__.py` — **CLI entrypoint** (`argparse`; runs the server via `uvicorn`).
- `bridge.py` — the FastAPI app: `build_app(provider)` and module-level `app`.
  Routes `/healthz`, `/quota`, and a catch-all `/{path:path}` proxy. Handles
  system-prefix injection, optional billing-attribution rewriting
  (`WCB_CC_BILLING_ATTRIBUTION`), optional tool-name prefixing
  (`WCB_CC_TOOL_RENAME`), extended-thinking body normalization, and both
  streaming (buffer-and-retry / incremental) and non-streaming forwarding.
- `credentials.py` — OAuth credential loading, refresh, single-account
  (`CredentialProvider`) and multi-account (`MultiAccountCredentialProvider`,
  via `WCB_CC_ACCOUNT_POOL`) providers.
- `errors.py` — maps Anthropic HTTP+body responses to an `ErrorKind`
  (transient throttle vs subscription cap vs token-invalid, etc.).
- `recovery.py` — a `run_with_recovery(fn, ...)` wrapper for a *client-side*
  caller: pauses-and-resumes on subscription-cap rate-limit errors by polling
  the bridge's `/quota`. Active only when `ANTHROPIC_API_BASE` points at a local
  bridge. (Written against litellm/openai exception types.)
- `stream_tee.py` — observe-only SSE tee for a live token feed; inert unless
  `WCB_CC_STREAM_LOG_PATH` is set. Never mutates forwarded bytes.

## (b) How to run it

Entrypoint is `claude_oauth/__main__.py`. Defaults (from its `argparse`):
`--host 127.0.0.1`, **`--port 8765`**, `--log-level info`, plus `--check`
(verify credentials load, then exit).

```sh
# From this vendor/ccbridge/ directory (so `claude_oauth` is importable):
python -m claude_oauth --check                 # verify credentials only
python -m claude_oauth --port 8765             # start the proxy (default port)
```

(The upstream `argparse` `prog` string still reads `python -m src.utils.claude_oauth`
— cosmetic, from the origin project. In this vendored layout the importable
package is `claude_oauth`.)

`bridge.py` also exposes a module-level `app = build_app()`, so it can be served
by any ASGI runner, e.g. `uvicorn claude_oauth.bridge:app --host 127.0.0.1 --port 8765`.

On start it prints the client wiring it expects:

```sh
export ANTHROPIC_API_BASE=http://127.0.0.1:8765
export ANTHROPIC_API_KEY=kaiju-cc-stub     # any non-empty stub; bridge strips it
```

### Credentials / env vars it needs

Credential sources, in priority order (`credentials.py::load_credentials`):

1. `CLAUDE_CODE_CREDENTIALS` — inline JSON (tests/CI).
2. `WCB_CC_CREDS_PATH` — path to a credentials JSON file.
3. `~/.claude/.credentials.json` — primary source on Linux (plaintext, written
   by the `claude` CLI).
4. macOS Keychain, service `Claude Code-credentials` (via `security find-generic-password`).
5. Linux Secret Service (`secret-tool`, optional/desktop only).
6. `~/.cache/wildclawbench/claude_creds.json` — bridge refresh cache (last).

Prerequisite: the user has signed in with the `claude` CLI so a Claude Code
OAuth token (`sk-ant-oat01-…`) exists in one of those sources. No
`ANTHROPIC_API_KEY` value is used upstream — the caller-supplied key is only a
non-empty stub and is stripped before forwarding.

Notable optional env knobs (all read in `bridge.py`, defaults noted):

- `WCB_CC_BRIDGE_SECRET` — shared secret; if unset the bridge is
  **unauthenticated** (any local process can spend the subscription). It always
  binds `127.0.0.1`.
- `WCB_CC_UPSTREAM` (default `https://api.anthropic.com`),
  `WCB_CC_ACCOUNT_POOL` (multi-account failover spec),
  `WCB_CC_BILLING_ATTRIBUTION` / `WCB_CC_TOOL_RENAME` / `WCB_CC_BUFFER_AND_RETRY`
  (default on), `WCB_CC_SKIP_SYSTEM_PREFIX`, `WCB_CC_STREAM_LOG_PATH`, and the
  `WCB_BRIDGE_*_TIMEOUT` tuning vars.

Runtime deps observed in imports: `fastapi`, `uvicorn`, `httpx`. (No Dockerfile,
README, or dependency manifest was present in the upstream directory — only the
`claude_oauth/*.py` package was vendored.)

## (c) Which complex-mcp components would point at it

- **`benchmark/rubric_judge.py::_default_llm_grader`** — the rubric LLM grader.
  It builds an Anthropic Messages request and would forward through this bridge
  if pointed at it. **Today it does not**: it shells out to the local `claude`
  CLI (`CLAUDE_BIN`, default `claude`) with `-p --model … --output-format json
  --dangerously-skip-permissions` and parses the CLI's JSON `result`. It uses no
  `ANTHROPIC_API_BASE`/`ANTHROPIC_API_KEY` override, so ccbridge is not in the
  path unless deliberately wired in.
- **A future Docker/container runner** — the natural consumer. A containerised
  trial with no host `claude` CLI would run this bridge and set
  `ANTHROPIC_API_BASE=http://<bridge-host>:8765` (+ a stub `ANTHROPIC_API_KEY`,
  + `WCB_CC_BRIDGE_SECRET` if locking down) so trial API traffic draws on the
  Claude Code subscription.

Note: the caller points at the bridge with **`ANTHROPIC_API_BASE`** (the var the
bridge prints and that `recovery.py` reads). The task brief mentions
`ANTHROPIC_BASE_URL`; the vendored code uses `ANTHROPIC_API_BASE`.

## (d) Status: OPTIONAL

ccbridge is currently **optional and unused** by complex-mcp. The LLM grader in
`rubric_judge.py` shells out to the local `claude` CLI on the host today; nothing
in complex-mcp imports `claude_oauth` or sets `ANTHROPIC_API_BASE` at it. This is
vendored to enable subscription-backed, container-friendly LLM calls later
(e.g. a Docker runner), not to change current behavior.
