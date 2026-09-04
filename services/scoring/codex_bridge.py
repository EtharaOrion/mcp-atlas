"""Route the rubric judge through a Codex subscription instead of a metered key.

`CodingForMoney/codex-bridge` runs a local server that exposes the Anthropic
Messages API and the OpenAI Responses API on top of an already-signed-in Codex
installation. Requests are fulfilled from `~/.codex/auth.json`, so grading bills
a ChatGPT plan rather than API credits. It replaces the Claude Code plan the
rubric judge used to bill through `CLAUDE_CODE_OAUTH_TOKEN`; that path is gone,
and the judge now posts at the bridge directly.

Three properties of this particular bridge drive everything below.

**It has no `/v1/chat/completions`.** It serves `/v1/messages` and
`/v1/responses` only. `rubric_judge._call_judge_once` calls
`litellm.completion`, which for an `openai/`-prefixed model posts to
`chat/completions` and would get a 404 here. The Codex models must therefore
route through litellm's `anthropic/` provider, which posts to `/v1/messages`.
`provider_route` is the single place that decides this.

**The Anthropic path takes a different base URL.** litellm appends
`/v1/messages` itself, so its `api_base` is the server root with no `/v1`. An
OpenAI Responses client wants `/v1`. Two constants exist for that reason, and
conflating them produces a 404 that looks like a model error.

**The API key is mandatory and generated, not chosen.** Every route except
`/health` requires it. The bridge writes it to `~/.cb/config.json` on first use
and prints it on `serve`. `api_key()` reads that file so an operator does not
have to copy it by hand, which is the step where a stale key silently ends up
in the environment.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Server root. The bridge binds 127.0.0.1:3456 unless CODEX_BRIDGE_HOST and
# CODEX_BRIDGE_PORT say otherwise.
DEFAULT_BRIDGE_ROOT = "http://127.0.0.1:3456"

# litellm's anthropic provider appends /v1/messages, so it wants the root.
# An OpenAI Responses client wants the versioned prefix. Keep both explicit.
DEFAULT_ANTHROPIC_BASE_URL = DEFAULT_BRIDGE_ROOT
DEFAULT_OPENAI_BASE_URL = f"{DEFAULT_BRIDGE_ROOT}/v1"

# The bridge serves exactly these two and rejects anything else with
# CODEX_MODEL_UNAVAILABLE before it contacts upstream, so a typo fails fast
# rather than after a full eval.
CODEX_MODELS = ("gpt-5.6-sol", "gpt-5.6-luna")
DEFAULT_BRIDGE_MODEL = "gpt-5.6-sol"

# Where the bridge stores the key it generates on first use (0600, in a 0700
# directory). Read rather than required from the environment so the operator
# does not hand-copy it.
CB_CONFIG = Path.home() / ".cb" / "config.json"
CODEX_AUTH_JSON = Path(
    os.environ.get("CODEX_HOME") or (Path.home() / ".codex")
) / "auth.json"

# The bundle's docker-compose mounts this whole directory read-only at
# /harness/scoring, so a file dropped beside this module is visible to the judge
# running inside the task container. That is the only channel into the verifier
# that does not require editing a shipped task.toml, and editing one would
# change the bundle digest that memory/crucible_view.yaml pins in
# task_artifact_hashes. Config travels with the scoring code instead.
#
# Gitignored: it carries the local bridge key. Written by `make judge-config`.
JUDGE_BACKEND_CONFIG = Path(__file__).resolve().parent / "judge_backend.json"

INSTALL_COMMAND = "npm install --global codex-anthropic-bridge"
START_COMMAND = "codex-bridge serve"


class BridgeUnavailable(RuntimeError):
    """The judge backend is not usable. Raised before any grading happens."""


def provider_route(model: str) -> str:
    """The litellm model string for a judge model.

    A Codex model routes through `anthropic/`, because the bridge serves
    Anthropic Messages and has no chat/completions endpoint.

    A name that already carries a provider is passed through untouched, so an
    operator pointing the judge at some other backend entirely is still able to.

    Any other bare name raises. It used to fall back to `openai/`, which was
    right when the judge talked to an OpenAI-compatible endpoint and is wrong
    now: this bridge has no chat/completions route, so such a name would 404 on
    every criterion. `score_rubric` counts judge errors rather than raising, so
    those 404s would arrive as a complete-looking report with a meaningless
    reward. Refusing here converts that into one loud failure at startup.
    """
    if model in CODEX_MODELS:
        return f"anthropic/{model}"
    if "/" in model:
        return model
    raise BridgeUnavailable(
        f"{model!r} is not a model this judge can reach. codex-bridge serves "
        f"{list(CODEX_MODELS)} and exposes no chat/completions route, so a bare "
        "name outside that pair would fail on every criterion. Use one of those, "
        "or give an explicit litellm provider prefix to target another backend."
    )


def load_config() -> dict:
    """The mounted judge-backend config, or an empty mapping.

    Absent is normal and not an error: an operator who exports the environment
    directly never needs this file.
    """
    try:
        data = json.loads(JUDGE_BACKEND_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve(name: str, explicit: str | None = None) -> str | None:
    """One resolution order for every judge-backend setting.

    Explicit argument, then environment, then the mounted config, then nothing.
    The environment wins over the file so a run can override per-invocation
    without rewriting a file that other runs share.
    """
    if explicit:
        return explicit
    env = os.environ.get(name)
    if env:
        return env
    value = load_config().get(name)
    return value if isinstance(value, str) and value else None


def anthropic_base(root: str) -> str:
    """The server root litellm's anthropic provider expects.

    It appends `/v1/messages` itself, so a base already carrying `/v1` becomes
    `.../v1/v1/messages`. The legacy default is written in the `/v1` form, so
    this is the live case rather than a guard against a typo.
    """
    trimmed = root.rstrip("/")
    return trimmed[: -len("/v1")] if trimmed.endswith("/v1") else trimmed


def resolve_endpoint(
    model: str, explicit_base: str | None = None, explicit_key: str | None = None
) -> tuple[str, str] | None:
    """The (base, key) a Codex model needs, or None when the model is not one.

    Used by both judges: rubric_judge_cli._preflight and score_rubric. Both
    refuse rather than proceed for the same reason:
    `score_rubric` counts per-criterion errors instead of raising, so a bridge
    that cannot be reached produces a full rubric of failures and still writes a
    score file. That reads like a graded run.

    Returns None for a non-Codex model so an operator pointing the judge
    somewhere else entirely is unaffected.
    """
    if model not in CODEX_MODELS:
        return None
    root = resolve("EVAL_LLM_BASE_URL", explicit_base) or DEFAULT_ANTHROPIC_BASE_URL
    key = api_key(explicit_key)
    if not key:
        raise BridgeUnavailable(
            f"{model} is served by codex-bridge, which requires an API key on every "
            "route, and none was found in the environment, ~/.cb/config.json, or the "
            f"judge config mounted at {JUDGE_BACKEND_CONFIG}. Run `make judge-config`."
        )
    return anthropic_base(root), key


def api_key(explicit: str | None = None) -> str | None:
    """The bridge key: an explicit value, then the environment, then its file."""
    if explicit:
        return explicit
    for name in ("CB_API_KEY", "EVAL_LLM_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value
    for name in ("EVAL_LLM_API_KEY", "CB_API_KEY"):
        value = load_config().get(name)
        if isinstance(value, str) and value:
            return value
    try:
        data = json.loads(CB_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for key in ("apiKey", "api_key", "key"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


@dataclass
class BridgeStatus:
    root: str
    model: str
    reachable: bool
    authenticated: bool
    model_available: bool
    models_listed: list[str]
    detail: str

    def as_record(self) -> dict:
        """The block a run should store next to its scores.

        The bridge's own README calls the ChatGPT-authenticated Codex backend
        "not a documented stable third-party API", so a run that grades through
        it cannot claim a pinned judge. Recording which endpoint and model
        actually answered is the most a run can honestly say.
        """
        return {
            "judge_backend": "codex-bridge",
            "root": self.root,
            "model": self.model,
            "transport": "anthropic-messages",
            "reachable": self.reachable,
            "authenticated": self.authenticated,
            "model_available": self.model_available,
            "models_listed": self.models_listed,
            "backend_pinned": False,
            "backend_note": (
                "local bridge over a ChatGPT-authenticated Codex login, which upstream "
                "describes as not a documented stable third-party API; the judge is "
                "therefore not pinned"
            ),
        }


def bridge_env(root: str | None = None, model: str | None = None) -> dict[str, str]:
    """The environment `score_rubric` reads, resolved for this bridge.

    EVAL_LLM_BASE_URL carries the server root and not the `/v1` prefix, because
    the Codex models route through litellm's anthropic provider and it appends
    `/v1/messages` itself.
    """
    key = api_key() or ""
    return {
        "EVAL_LLM_BASE_URL": root or DEFAULT_ANTHROPIC_BASE_URL,
        "EVAL_LLM_API_KEY": key,
        "JUDGE_MODEL": model or DEFAULT_BRIDGE_MODEL,
    }


def _get(url: str, timeout: float, key: str | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    if key:
        req.add_header("x-api-key", key)
        req.add_header("Authorization", f"Bearer {key}")
    try:
        if req.type not in ("http", "https"):
            raise ValueError(f"refusing non-HTTP(S) URL scheme: {req.full_url!r}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def check(
    root: str | None = None,
    model: str | None = None,
    timeout: float = 5.0,
    key: str | None = None,
) -> BridgeStatus:
    """Probe the bridge without raising. Returns what was observed."""
    base = (root or DEFAULT_ANTHROPIC_BASE_URL).rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    want = model or DEFAULT_BRIDGE_MODEL
    token = api_key(key)

    try:
        status, _body = _get(f"{base}/health", timeout)
    except (urllib.error.URLError, OSError, ValueError) as e:
        return BridgeStatus(
            base, want, False, False, False, [],
            f"no server answered at {base}/health: {e}. Install it with "
            f"`{INSTALL_COMMAND}` and start it with `{START_COMMAND}`",
        )
    if status != 200:
        return BridgeStatus(
            base, want, False, False, False, [],
            f"{base}/health returned HTTP {status}, so the server is up but unhealthy",
        )

    if not token:
        return BridgeStatus(
            base, want, True, False, False, [],
            "the server is up but no API key was found. Every route except /health "
            f"requires one. It is printed by `{START_COMMAND}` and stored at "
            f"{CB_CONFIG}; set CB_API_KEY or EVAL_LLM_API_KEY to override",
        )

    mstatus, mbody = _get(f"{base}/v1/models", timeout, token)
    if mstatus in (401, 403):
        return BridgeStatus(
            base, want, True, False, False, [],
            f"the server rejected the API key with HTTP {mstatus}. If it was rotated "
            f"with `codex-bridge key refresh`, re-read it from {CB_CONFIG}",
        )
    listed: list[str] = []
    try:
        payload = json.loads(mbody)
        listed = [
            str(m.get("id")) for m in payload.get("data", []) if isinstance(m, dict)
        ]
    except (ValueError, json.JSONDecodeError):
        listed = []

    available = want in listed
    if listed and not available:
        detail = (
            f"authenticated, but {want!r} is not among the model(s) the server serves "
            f"({listed}). This bridge serves a fixed pair and rejects anything else "
            "with CODEX_MODEL_UNAVAILABLE, so this model will not grade"
        )
    elif not listed:
        detail = "authenticated, but the model listing returned nothing parsable"
    else:
        detail = f"authenticated and {want!r} is served"
    return BridgeStatus(base, want, True, True, available, listed, detail)


def preflight(
    root: str | None = None,
    model: str | None = None,
    timeout: float = 5.0,
    require_auth_file: bool = True,
) -> BridgeStatus:
    """Refuse to start grading unless the judge backend can actually answer.

    Raises `BridgeUnavailable` naming the fix. This matters more than it looks:
    `score_rubric` catches per-criterion errors and counts them in
    `judge_failures`, then returns a reward computed from whatever succeeded. A
    stopped or unauthenticated bridge therefore yields a complete-looking report
    whose numbers came from almost nothing. One loud failure here is cheaper
    than a full eval that has to be thrown away, and cheaper still than one that
    is not noticed.

    Unlike the reachability and auth checks, an unserved model is fatal: this
    bridge serves a fixed pair and refuses everything else before it contacts
    upstream, so continuing would fail every criterion.
    """
    if require_auth_file and not CODEX_AUTH_JSON.is_file():
        raise BridgeUnavailable(
            f"{CODEX_AUTH_JSON} does not exist, so the bridge has no Codex credentials "
            "to fulfil requests with. Sign in through Codex itself; this bridge has no "
            "login subcommand and never writes auth.json."
        )
    status = check(root, model, timeout)
    if not status.reachable or not status.authenticated:
        raise BridgeUnavailable(status.detail)
    if status.models_listed and not status.model_available:
        raise BridgeUnavailable(status.detail)
    return status
