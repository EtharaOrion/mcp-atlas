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
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
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
# The models this bridge will route. Must agree with
# rubric_judge_cli.CODEX_MODELS, which is the authoritative list because the
# judge grades over the local codex CLI rather than over this bridge. The two
# disagreed -- this carried gpt-5.6-luna and the CLI did not -- so a JUDGE_MODEL
# of gpt-5.6-luna was accepted for routing here and rejected at the CLI, which
# is one half of C-GAP-JUDGE-TRANSPORT-UNPINNED. luna is removed rather than
# added to the CLI: the CLI is authoritative, and a bridge that advertises a
# model the grading path cannot reach is the more dangerous direction.
CODEX_MODELS = ("gpt-5.6-sol",)
DEFAULT_BRIDGE_MODEL = "gpt-5.6-sol"

# Where the bridge stores the key it generates on first use (0600, in a 0700
# directory). Read rather than required from the environment so the operator
# does not hand-copy it.
CB_CONFIG = Path.home() / ".cb" / "config.json"
CODEX_AUTH_JSON = Path(
    os.environ.get("CODEX_HOME") or (Path.home() / ".codex")
) / "auth.json"

# Judge-backend config. HOST-ONLY, and deliberately not beside this module.
#
# It used to live at `services/scoring/judge_backend.json` on the argument that
# the compose mount at /harness/scoring was the only channel into the verifier
# that did not require editing a shipped task.toml. Three facts retired that
# argument, and they are recorded here because the file carries a live key:
#
# 1. The verifier is not a separate container. Every bundle's task.toml sets
#    `[verifier] environment_mode = "shared"`, and TASK_BUNDLE.md describes
#    `main` as "the `main` container the agent + verifier run in" -- harbor
#    execs the agent, then the verifier, inside the same container. So a secret
#    under /harness/scoring is readable by the graded agent for the whole run,
#    not merely by the verifier.
#
# 2. Nothing inside that container reads this file. The only grader
#    `tests/test.sh` invokes is rubric_judge_cli.py, which does not import this
#    module; it grades over the local `codex` CLI on the host or the `claude`
#    CLI in the container, taking CLAUDE_CODE_OAUTH_TOKEN from [verifier.env].
#    The only importers of codex_bridge are harness/Makefile and
#    scripts/judge_smoke_test.py, both host-side. The key was exposed for no
#    consumer.
#
# 3. The digest that supposedly forbade the alternative does not exist. The
#    Amandeep bundle -- the only one that ships -- carries no entry in
#    .memory/crucible_view.yaml task_artifact_hashes, which is the standing
#    finding C-GAP-VIEW-MISSING-TASK-HASH-AMANDEEP. There was no binding to
#    break.
#
# So it moves beside the bridge's own key file, which is already 0600 in a 0700
# directory and is not mounted anywhere. Written by `make judge-config`.
JUDGE_BACKEND_CONFIG = Path.home() / ".cb" / "judge_backend.json"

# The path it used to live at, retained only so a stale copy is reported rather
# than read. Reading it would re-establish the exposure this move removed, and
# would do so silently, so `load_config` refuses it and `preflight` fails on it.
MOUNTED_LEGACY_CONFIG = Path(__file__).resolve().parent / "judge_backend.json"


def mounted_secret_leak() -> Path | None:
    """The legacy in-tree config, if an operator still has one on disk.

    Returns the path rather than a bool so callers can name it in the message
    an operator has to act on. The check is existence-only and does not read the
    file: whether it happens to carry a key today is not the point, the mount is.
    """
    try:
        return MOUNTED_LEGACY_CONFIG if MOUNTED_LEGACY_CONFIG.is_file() else None
    except OSError:
        return None

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
        "name outside that list would fail on every criterion. Use one of those, "
        "or give an explicit litellm provider prefix to target another backend."
    )


def load_config() -> dict:
    """The host-side judge-backend config, or an empty mapping.

    Absent is normal and not an error: an operator who exports the environment
    directly never needs this file.

    A stale copy at the old in-tree path is warned about and NOT read. Reading
    it would work -- the values are the same shape -- and that is exactly the
    problem: the run would succeed while a live key sat inside a mount the
    graded agent can read, with nothing in the output saying so. Refusing makes
    the operator delete it.
    """
    stale = mounted_secret_leak()
    if stale is not None:
        print(
            f"[codex_bridge] ignoring {stale}: it is inside the tree that "
            "docker-compose mounts read-only at /harness/scoring, and the "
            "verifier shares a container with the graded agent, so anything "
            "there is agent-readable. Delete it and run `make judge-config`, "
            f"which now writes {JUDGE_BACKEND_CONFIG}.",
            file=sys.stderr,
        )
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


# ---------------------------------------------------------------- pinnability
#
# `backend_pinned` used to be the literal False in the record below. A constant
# is not a determination: it reads the same whether someone evaluated the
# backend or typed a pessimistic default, and it cannot become true when the
# backend changes. C-GAP-JUDGE-TRANSPORT-UNPINNED capped at HOLD partly for
# that reason. The predicate is stated here instead, and the record carries the
# per-criterion result so a reader can check the conclusion against the basis.
#
# A judge backend is pinned when BOTH hold:
#
#   documented_stable_api      The backend's API is published and versioned, so
#                              the behaviour a trial measured is the behaviour a
#                              re-run gets. codex-bridge fails this on upstream's
#                              own statement: its README calls the
#                              ChatGPT-authenticated Codex backend "not a
#                              documented stable third-party API".
#
#   resolvable_build_identity  The serving build reports an identity a run can
#                              record, so two runs can be told apart. Observed
#                              from /health rather than assumed; absent is
#                              recorded as unestablished, never as satisfied.
#
# Both must hold, so this bridge is not pinnable today and the first criterion
# is the reason. That is a property of the backend, not a defect in this file:
# no code here can make an undocumented API documented, and pretending otherwise
# by flipping the flag would be the failure this predicate exists to prevent.
PIN_CRITERIA = ("documented_stable_api", "resolvable_build_identity")

# Upstream's own characterisation, quoted rather than paraphrased because it is
# the whole basis for the first criterion failing.
_UPSTREAM_STABILITY_NOTE = (
    "codex-bridge's README describes the ChatGPT-authenticated Codex backend as "
    "'not a documented stable third-party API'"
)


def pin_assessment(server_identity: dict | None = None) -> dict:
    """Whether this backend is pinnable, and on what basis.

    Derived, not declared. `server_identity` is whatever /health reported;
    an empty mapping means the build identity was not established, which is
    recorded as a failed criterion rather than glossed as a pass.
    """
    identity = server_identity or {}
    build = identity.get("version") or identity.get("build") or None
    criteria = {
        "documented_stable_api": False,
        "resolvable_build_identity": bool(build),
    }
    return {
        "pinned": all(criteria.values()),
        "criteria": criteria,
        "build_identity": build,
        "basis": {
            "documented_stable_api": _UPSTREAM_STABILITY_NOTE,
            "resolvable_build_identity": (
                f"/health reported {build!r}" if build
                else "/health reported no version or build field"
            ),
        },
    }


@dataclass
class BridgeStatus:
    root: str
    model: str
    reachable: bool
    authenticated: bool
    model_available: bool
    models_listed: list[str]
    detail: str
    # Whatever /health reported about itself. Empty when the probe did not get
    # that far or the body carried nothing identifying; the pin assessment
    # reads the difference rather than assuming either way.
    server_identity: dict = field(default_factory=dict)

    def as_record(self) -> dict:
        """The block a run should store next to its scores.

        Two things this record has to get right, because both were wrong before.

        The pin verdict is DERIVED. `pin_assessment` states the predicate and
        returns the per-criterion result, so a reader can check the conclusion
        rather than take the flag on trust, and so the verdict can move if the
        backend ever does. `backend_pinned` is kept as a top-level key because
        consumers read it, but it is now computed from that assessment.

        The SCOPE is stated. This bridge is not the transport that grades a
        scored run, and a record that omits that invites the opposite reading --
        that the graded judge was unpinned via this path. `tests/test.sh` invokes
        rubric_judge_cli.py, which reaches a model over the local `codex` or
        `claude` CLI and never imports this module; the only importers are
        harness/Makefile and scripts/judge_smoke_test.py. So this record covers
        the smoke and preflight path. The graded path has its own record, in
        rubric_judge_cli.pin_record, and neither substitutes for the other.
        """
        assessment = pin_assessment(self.server_identity)
        return {
            "judge_backend": "codex-bridge",
            "root": self.root,
            "model": self.model,
            "transport": "anthropic-messages",
            "reachable": self.reachable,
            "authenticated": self.authenticated,
            "model_available": self.model_available,
            "models_listed": self.models_listed,
            "backend_pinned": assessment["pinned"],
            "pin_assessment": assessment,
            "covers": "smoke-and-preflight",
            "grading_path": (
                "not this module. A scored run grades through "
                "rubric_judge_cli.py over the local codex or claude CLI; see "
                "rubric_judge_cli.pin_record for that path's pin record"
            ),
            "backend_note": (
                "local bridge over a ChatGPT-authenticated Codex login; "
                f"{_UPSTREAM_STABILITY_NOTE}, so the documented_stable_api "
                "criterion fails and the backend is not pinnable"
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

    identity: dict = {}
    try:
        status, health_body = _get(f"{base}/health", timeout)
        # Best-effort. A body that is not JSON, or JSON that names no version,
        # leaves identity empty, and pin_assessment reports that criterion as
        # unmet rather than inventing a build.
        try:
            parsed = json.loads(health_body)
            if isinstance(parsed, dict):
                identity = parsed
        except (ValueError, json.JSONDecodeError):
            identity = {}
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
    return BridgeStatus(base, want, True, True, available, listed, detail, identity)


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
    stale = mounted_secret_leak()
    if stale is not None:
        raise BridgeUnavailable(
            f"{stale} exists. That directory is bind-mounted read-only at "
            "/harness/scoring, and task.toml sets [verifier] environment_mode = "
            "'shared', so the verifier runs in the same container as the graded "
            "agent and the file is agent-readable for the whole run. It carries "
            "the bridge API key. Nothing in the container reads it -- "
            "rubric_judge_cli.py does not import this module -- so it is "
            f"exposure with no consumer. Delete it; `make judge-config` now "
            f"writes {JUDGE_BACKEND_CONFIG}, which is not mounted anywhere."
        )
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
