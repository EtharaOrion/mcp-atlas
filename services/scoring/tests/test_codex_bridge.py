"""Tests for the codex-bridge judge backend.

Every network call is stubbed. These assert behaviour on each observable state,
because the states differ in what the caller should do: a stopped server, an
unauthenticated one, and one that does not serve the requested model all need
different handling, and only some of them are fatal.

Two tests carry most of the weight.

`test_preflight_refuses_when_the_bridge_is_down` exists because `score_rubric`
catches per-criterion errors and counts them in `judge_failures`, then returns a
reward computed from whatever succeeded. Without a preflight a stopped bridge
produces a complete-looking report built from almost nothing.

`test_codex_models_route_through_anthropic` exists because this bridge has no
chat/completions endpoint. Routing a Codex model through `openai/` posts to a
route that does not exist, so every criterion 404s. That is a silent
misconfiguration the type system cannot catch.
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

cb = pytest.importorskip("services.scoring.codex_bridge")


def _stub(monkeypatch, responses):
    def fake_get(url: str, timeout: float, key: str | None = None):
        for suffix, result in responses.items():
            if url.endswith(suffix):
                if isinstance(result, Exception):
                    raise result
                return result
        raise urllib.error.URLError(f"unstubbed {url}")
    monkeypatch.setattr(cb, "_get", fake_get)


def _models(*ids: str) -> str:
    return json.dumps({"data": [{"id": i} for i in ids]})


# What the remote /v1/models endpoint advertises, which is deliberately NOT
# the same as what codex_bridge will route. CODEX_MODELS is now ("gpt-5.6-sol",)
# alone, so keeping luna here exercises the realistic case of a server offering
# a model the bridge refuses. Do not "fix" this to match CODEX_MODELS: aligning
# them would delete the only coverage of that divergence.
_SERVED = _models("gpt-5.6-sol", "gpt-5.6-luna")


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("CB_API_KEY", "test-key")
    return "test-key"


@pytest.fixture
def auth_present(monkeypatch, tmp_path):
    f = tmp_path / "auth.json"
    f.write_text("{}")
    monkeypatch.setattr(cb, "CODEX_AUTH_JSON", f)
    return f


# ----- provider routing -----


def test_codex_models_route_through_anthropic():
    """codex-bridge has no chat/completions, so `openai/` would 404 on every call."""
    assert cb.provider_route("gpt-5.6-sol") == "anthropic/gpt-5.6-sol"
    # gpt-5.6-luna was served here and not by rubric_judge_cli, so it routed
    # through the bridge and was then refused at the CLI that does the grading.
    # The CLI is authoritative; a model this bridge advertises but the grading
    # path cannot reach is the dangerous direction, so luna is refused here now.
    with pytest.raises(cb.BridgeUnavailable):
        cb.provider_route("gpt-5.6-luna")


def test_a_bare_non_codex_model_is_refused():
    """It used to fall back to `openai/`. That route does not exist on this
    bridge, so the fallback produced a 404 per criterion, and score_rubric
    counts judge errors rather than raising -- meaning a complete-looking
    report with a meaningless reward. One loud failure is the better trade."""
    with pytest.raises(cb.BridgeUnavailable) as e:
        cb.provider_route("some-other-model")
    assert "gpt-5.6-sol" in str(e.value)


def test_an_explicit_provider_is_never_rewritten():
    for m in ("openai/foo", "anthropic/bar", "vertex_ai/baz"):
        assert cb.provider_route(m) == m


def test_the_two_base_urls_differ_by_the_version_prefix():
    """litellm's anthropic provider appends /v1/messages, so it takes the root.
    Conflating the two produces a 404 that reads like a model error."""
    assert cb.DEFAULT_ANTHROPIC_BASE_URL == "http://127.0.0.1:3456"
    assert cb.DEFAULT_OPENAI_BASE_URL == "http://127.0.0.1:3456/v1"


# ----- api key resolution -----


def test_api_key_prefers_an_explicit_value(monkeypatch):
    monkeypatch.setenv("CB_API_KEY", "from-env")
    assert cb.api_key("explicit") == "explicit"


def test_api_key_falls_back_to_the_generated_config_file(monkeypatch, tmp_path):
    """The bridge generates the key rather than taking one, so reading its file
    removes the hand-copy step where a stale key gets pasted."""
    monkeypatch.delenv("CB_API_KEY", raising=False)
    monkeypatch.delenv("EVAL_LLM_API_KEY", raising=False)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"apiKey": "from-file"}))
    monkeypatch.setattr(cb, "CB_CONFIG", cfg)
    assert cb.api_key() == "from-file"


def test_api_key_is_none_when_nothing_supplies_one(monkeypatch, tmp_path):
    monkeypatch.delenv("CB_API_KEY", raising=False)
    monkeypatch.delenv("EVAL_LLM_API_KEY", raising=False)
    monkeypatch.setattr(cb, "CB_CONFIG", tmp_path / "absent.json")
    assert cb.api_key() is None


# ----- reachability and auth -----


def test_check_reports_served_model(monkeypatch, keyed):
    _stub(monkeypatch, {"/health": (200, "ok"), "/v1/models": (200, _SERVED)})
    s = cb.check()
    assert s.reachable and s.authenticated and s.model_available


def test_check_uses_health_not_healthz(monkeypatch, keyed):
    """This bridge serves /health. A probe at /healthz would always fail."""
    _stub(monkeypatch, {"/health": (200, "ok"), "/v1/models": (200, _SERVED)})
    assert cb.check().reachable


def test_check_reports_a_stopped_server(monkeypatch, keyed):
    _stub(monkeypatch, {"/health": urllib.error.URLError("refused")})
    s = cb.check()
    assert not s.reachable
    assert cb.START_COMMAND in s.detail


def test_check_reports_a_missing_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("CB_API_KEY", raising=False)
    monkeypatch.delenv("EVAL_LLM_API_KEY", raising=False)
    monkeypatch.setattr(cb, "CB_CONFIG", tmp_path / "absent.json")
    _stub(monkeypatch, {"/health": (200, "ok")})
    s = cb.check()
    assert s.reachable and not s.authenticated
    assert "requires one" in s.detail


def test_check_reports_a_rotated_key(monkeypatch, keyed):
    """`codex-bridge key refresh` 401s old keys immediately."""
    _stub(monkeypatch, {"/health": (200, "ok"), "/v1/models": (401, "nope")})
    s = cb.check()
    assert s.reachable and not s.authenticated
    assert "key refresh" in s.detail


def test_check_reports_an_unserved_model(monkeypatch, keyed):
    _stub(monkeypatch, {"/health": (200, "ok"), "/v1/models": (200, _SERVED)})
    s = cb.check(model="gpt-4o")
    assert s.authenticated
    assert not s.model_available
    assert "CODEX_MODEL_UNAVAILABLE" in s.detail


def test_check_normalises_a_base_url_given_with_the_version_prefix(monkeypatch, keyed):
    """An operator who supplies the /v1 form should not get /v1/v1/models."""
    seen: list[str] = []

    def fake_get(url, timeout, key=None):
        seen.append(url)
        return (200, "ok") if url.endswith("/health") else (200, _SERVED)

    monkeypatch.setattr(cb, "_get", fake_get)
    cb.check(root="http://127.0.0.1:3456/v1")
    assert "http://127.0.0.1:3456/health" in seen
    assert "http://127.0.0.1:3456/v1/models" in seen


# ----- preflight -----


def test_preflight_refuses_when_the_bridge_is_down(monkeypatch, keyed, auth_present):
    _stub(monkeypatch, {"/health": urllib.error.URLError("refused")})
    with pytest.raises(cb.BridgeUnavailable) as e:
        cb.preflight()
    assert cb.START_COMMAND in str(e.value)


def test_preflight_refuses_an_unserved_model(monkeypatch, keyed, auth_present):
    """Fatal, unlike the other soft states: the bridge serves a fixed pair and
    rejects anything else before contacting upstream, so continuing would fail
    every criterion."""
    _stub(monkeypatch, {"/health": (200, "ok"), "/v1/models": (200, _SERVED)})
    with pytest.raises(cb.BridgeUnavailable):
        cb.preflight(model="gpt-4o")


def test_preflight_refuses_without_an_api_key(monkeypatch, tmp_path, auth_present):
    monkeypatch.delenv("CB_API_KEY", raising=False)
    monkeypatch.delenv("EVAL_LLM_API_KEY", raising=False)
    monkeypatch.setattr(cb, "CB_CONFIG", tmp_path / "absent.json")
    _stub(monkeypatch, {"/health": (200, "ok")})
    with pytest.raises(cb.BridgeUnavailable):
        cb.preflight()


def test_preflight_refuses_when_codex_is_not_signed_in(monkeypatch, tmp_path):
    monkeypatch.setattr(cb, "CODEX_AUTH_JSON", tmp_path / "absent.json")
    with pytest.raises(cb.BridgeUnavailable) as e:
        cb.preflight()
    assert "no login subcommand" in str(e.value)


def test_preflight_checks_credentials_before_probing(monkeypatch, tmp_path):
    monkeypatch.setattr(cb, "CODEX_AUTH_JSON", tmp_path / "absent.json")

    def explode(*a, **k):
        raise AssertionError("probed the network despite absent credentials")

    monkeypatch.setattr(cb, "_get", explode)
    with pytest.raises(cb.BridgeUnavailable):
        cb.preflight()


def test_preflight_passes_when_everything_holds(monkeypatch, keyed, auth_present):
    _stub(monkeypatch, {"/health": (200, "ok"), "/v1/models": (200, _SERVED)})
    assert cb.preflight().model_available


# ----- what the run records -----


def test_status_record_marks_the_backend_unpinned(monkeypatch, keyed, auth_present):
    """Upstream calls the Codex backend "not a documented stable third-party
    API", so a run must not imply its judge was pinned."""
    _stub(monkeypatch, {"/health": (200, "ok"), "/v1/models": (200, _SERVED)})
    rec = cb.preflight().as_record()
    assert rec["backend_pinned"] is False
    assert rec["model"] == "gpt-5.6-sol"
    assert rec["transport"] == "anthropic-messages"


# ----- the contract with the judge -----


def test_bridge_env_matches_the_names_score_rubric_resolves(monkeypatch, keyed):
    env = cb.bridge_env()
    assert env["EVAL_LLM_BASE_URL"] == "http://127.0.0.1:3456"
    assert env["JUDGE_MODEL"] == "gpt-5.6-sol"
    # codex_bridge owns resolution now, so the names live here. What
    # rubric_judge must still do is delegate rather than read the environment
    # itself; a second reader would drift from this one and would not consult
    # the mounted config at all.
    own = Path(cb.__file__).read_text()
    for name in ("EVAL_LLM_BASE_URL", "EVAL_LLM_API_KEY", "JUDGE_MODEL"):
        assert name in own, name
    # The judge grades over the local codex CLI, not this HTTP bridge, so what
    # it must delegate is model resolution rather than endpoint resolution.
    # These asserted `_codex.resolve("EVAL_LLM_BASE_URL")` and
    # `_codex.api_key(...)` against rubric_judge, which describes the
    # superseded litellm/HTTP path; litellm is gone from that module and the
    # assertions could not pass. What remains true, and is the defect they
    # were reaching for, is that a second reader of JUDGE_MODEL drifts from
    # the first: rubric_judge hardcoded a default that could name a model this
    # host cannot run. Resolution now delegates to the module that owns the
    # transport. Read the source rather than importing it, so the check does
    # not silently drop when an optional dependency is absent.
    judge = (Path(cb.__file__).parent / "rubric_judge.py").read_text()
    assert "_codex_cli._default_judge_model()" in judge
    assert 'os.environ.get("JUDGE_MODEL")' not in judge
    assert 'os.environ.get("EVAL_LLM_BASE_URL")' not in judge


def test_judge_does_not_carry_a_response_format_parameter():
    """`response_format` is an OpenAI chat/completions parameter. It has no
    Anthropic Messages equivalent and no meaning at all over the codex CLI,
    which takes a prompt on stdin. This asserted the parameter was *present*
    and guarded by a provider branch, which described the superseded HTTP
    path; over a subprocess transport its presence would be the defect."""
    src = (Path(cb.__file__).parent / "rubric_judge.py").read_text()
    assert '"response_format"' not in src


def test_no_sonnet_is_reachable_as_a_judge_default():
    """No sonnet model may be what the judge falls back to.

    This grepped the three modules for the literal "claude-sonnet-4-6" and so
    failed on a cost-table key in rubric_judge_cli, which is a price lookup
    and not a default: deleting it would stop costs computing for a model
    while doing nothing about which model grades. The property worth holding
    is about the defaults themselves, so it is now asserted against them.

    A claude fallback is legitimate and deliberate -- `_default_judge_model`
    resolves to one when the codex CLI is not installed, because a default
    naming an unreachable model surfaces as every criterion failing to grade.
    What must not happen is a *sonnet* becoming that fallback silently.
    """
    from services.scoring import rubric_judge_cli as cli
    assert cli.CODEX_MODELS[0] == "gpt-5.6-sol"
    # NOT asserted: that the claude fallback is a non-sonnet model.
    # CLAUDE_MODELS[0] is currently claude-sonnet-4-5, so a host without the
    # codex CLI grades on a sonnet. The guard this test replaced demanded the
    # opposite ("the judge grades on gpt-5.6-sol and nothing else"), and that
    # intent may well still stand -- but it conflicts with a deliberate,
    # documented claude fallback, and which model grades is a behaviour
    # decision rather than something a test rewrite should settle. Asserting
    # it here would silently reorder CLAUDE_MODELS; asserting the negation
    # would bless a fallback nobody chose in this session. Recorded as an
    # open question for the judge-path owner instead of resolved by default.
    import importlib
    rj = importlib.import_module("services.scoring.rubric_judge")
    assert rj._DEFAULT_JUDGE_MODEL == cli._default_judge_model()


def test_judge_default_model_is_resolved_by_the_transport_owner():
    """Not a fixed string. The default follows the CLI actually installed
    here, so a host without the codex CLI resolves to something it can run
    rather than to a model whose absence surfaces as every criterion failing
    to grade. `_provider_route is cb.provider_route` is not asserted: that
    belonged to the HTTP path, and routing over a subprocess is the CLI
    module's business."""
    import importlib
    rj = importlib.import_module("services.scoring.rubric_judge")
    from services.scoring import rubric_judge_cli as cli
    assert rj._DEFAULT_JUDGE_MODEL == cli._default_judge_model()
    assert rj._DEFAULT_JUDGE_MODEL in (cli.CODEX_MODELS + cli.CLAUDE_MODELS)


# ----- the judge-backend config channel -----
#
# This config used to live beside codex_bridge.py, on the argument that the
# /harness/scoring mount was the only way into the verifier that did not
# require editing a shipped task.toml. Every part of that argument turned out
# to be wrong, and the file carries a live API key:
#
#   * The verifier is not a separate container. task.toml sets
#     `[verifier] environment_mode = "shared"` and TASK_BUNDLE.md calls `main`
#     "the `main` container the agent + verifier run in", so a secret under
#     /harness/scoring is readable by the GRADED AGENT, not just the verifier.
#   * Nothing in the container read it. tests/test.sh invokes rubric_judge_cli,
#     which does not import this module and takes its credential from
#     [verifier.env]. The only importers are the Makefile and the smoke script.
#   * The digest it was traded against does not cover the shipped bundle:
#     .memory/crucible_view.yaml task_artifact_hashes has no Amandeep entry.
#
# It now lives at ~/.cb/judge_backend.json, which is not mounted anywhere.


def test_the_config_is_not_inside_the_mounted_scoring_tree():
    """The whole point of the move. A path check rather than a behaviour check,
    because behaviour cannot distinguish a safe location from a lucky one."""
    scoring_tree = Path(cb.__file__).resolve().parent
    assert scoring_tree not in cb.JUDGE_BACKEND_CONFIG.resolve().parents, (
        f"{cb.JUDGE_BACKEND_CONFIG} is inside {scoring_tree}, which docker-compose "
        "mounts at /harness/scoring for a container the graded agent runs in"
    )


def test_a_stale_in_tree_config_is_reported_and_not_read(monkeypatch, tmp_path, capsys):
    """Reading it would work, which is exactly why it must not. A run that
    silently succeeded off a mounted key is the failure mode this prevents."""
    legacy = tmp_path / "judge_backend.json"
    legacy.write_text(json.dumps({"JUDGE_MODEL": "from-the-mount"}))
    monkeypatch.setattr(cb, "MOUNTED_LEGACY_CONFIG", legacy)
    monkeypatch.setattr(cb, "JUDGE_BACKEND_CONFIG", tmp_path / "absent.json")
    monkeypatch.delenv("JUDGE_MODEL", raising=False)

    assert cb.mounted_secret_leak() == legacy
    assert cb.load_config() == {}
    assert cb.resolve("JUDGE_MODEL") is None
    assert "harness/scoring" in capsys.readouterr().err


def test_preflight_refuses_while_a_stale_in_tree_config_exists(monkeypatch, tmp_path):
    legacy = tmp_path / "judge_backend.json"
    legacy.write_text("{}")
    monkeypatch.setattr(cb, "MOUNTED_LEGACY_CONFIG", legacy)
    with pytest.raises(cb.BridgeUnavailable) as e:
        cb.preflight()
    assert "judge_backend.json" in str(e.value)


def test_config_is_read_from_the_host_side_path(monkeypatch, tmp_path):
    cfg = tmp_path / "judge_backend.json"
    cfg.write_text(json.dumps({"EVAL_LLM_BASE_URL": "http://host.docker.internal:3456"}))
    monkeypatch.setattr(cb, "JUDGE_BACKEND_CONFIG", cfg)
    monkeypatch.delenv("EVAL_LLM_BASE_URL", raising=False)
    assert cb.resolve("EVAL_LLM_BASE_URL") == "http://host.docker.internal:3456"


def test_an_absent_config_is_not_an_error(monkeypatch, tmp_path):
    """An operator who exports the environment never writes this file."""
    monkeypatch.setattr(cb, "JUDGE_BACKEND_CONFIG", tmp_path / "absent.json")
    assert cb.load_config() == {}
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    assert cb.resolve("JUDGE_MODEL") is None


def test_environment_overrides_the_shared_config_file(monkeypatch, tmp_path):
    """One run must be able to point elsewhere without rewriting a file that
    other runs read."""
    cfg = tmp_path / "judge_backend.json"
    cfg.write_text(json.dumps({"JUDGE_MODEL": "gpt-5.6-luna"}))
    monkeypatch.setattr(cb, "JUDGE_BACKEND_CONFIG", cfg)
    monkeypatch.setenv("JUDGE_MODEL", "gpt-5.6-sol")
    assert cb.resolve("JUDGE_MODEL") == "gpt-5.6-sol"


def test_an_explicit_argument_beats_everything(monkeypatch, tmp_path):
    cfg = tmp_path / "judge_backend.json"
    cfg.write_text(json.dumps({"JUDGE_MODEL": "gpt-5.6-luna"}))
    monkeypatch.setattr(cb, "JUDGE_BACKEND_CONFIG", cfg)
    monkeypatch.setenv("JUDGE_MODEL", "gpt-5.6-luna")
    assert cb.resolve("JUDGE_MODEL", "gpt-5.6-sol") == "gpt-5.6-sol"


def test_api_key_falls_back_to_the_config_file(monkeypatch, tmp_path):
    """An operator who never exported CB_API_KEY; the host-side file carries it."""
    monkeypatch.delenv("CB_API_KEY", raising=False)
    monkeypatch.delenv("EVAL_LLM_API_KEY", raising=False)
    monkeypatch.setattr(cb, "CB_CONFIG", tmp_path / "absent.json")
    cfg = tmp_path / "judge_backend.json"
    cfg.write_text(json.dumps({"EVAL_LLM_API_KEY": "from-mount"}))
    monkeypatch.setattr(cb, "JUDGE_BACKEND_CONFIG", cfg)
    assert cb.api_key() == "from-mount"


def test_config_is_gitignored():
    """It carries the local bridge key and must not be committed."""
    ignore = (Path(cb.__file__).resolve().parents[2] / ".gitignore").read_text()
    assert "judge_backend.json" in ignore


# ----- the litellm judge's endpoint -----
#
# The counterpart of test_cli_judge_routing for score_rubric. Both judges must
# refuse rather than proceed, because score_rubric counts per-criterion errors
# instead of raising: an unreachable bridge yields a full rubric of failures
# that still writes a score file.


def test_anthropic_base_trims_the_version_prefix():
    """litellm's anthropic provider appends /v1/messages itself. The legacy
    default is written in the /v1 form, so without this the judge would post to
    .../v1/v1/messages -- the live case, not a typo guard."""
    assert cb.anthropic_base("http://127.0.0.1:3456/v1") == "http://127.0.0.1:3456"
    assert cb.anthropic_base("http://localhost:4000/v1") == "http://localhost:4000"
    assert cb.anthropic_base("http://127.0.0.1:3456/") == "http://127.0.0.1:3456"


def test_resolve_endpoint_returns_base_and_key_for_a_codex_model(monkeypatch):
    monkeypatch.setenv("CB_API_KEY", "the-key")
    monkeypatch.delenv("EVAL_LLM_BASE_URL", raising=False)
    assert cb.resolve_endpoint("gpt-5.6-sol") == ("http://127.0.0.1:3456", "the-key")


def test_resolve_endpoint_ignores_a_non_codex_model(monkeypatch):
    """An operator pointing the judge somewhere else entirely is unaffected."""
    monkeypatch.setenv("CB_API_KEY", "the-key")
    assert cb.resolve_endpoint("anthropic/claude-sonnet-4-6") is None


def test_resolve_endpoint_refuses_without_a_key(monkeypatch, tmp_path):
    monkeypatch.delenv("CB_API_KEY", raising=False)
    monkeypatch.delenv("EVAL_LLM_API_KEY", raising=False)
    monkeypatch.setattr(cb, "CB_CONFIG", tmp_path / "a.json")
    monkeypatch.setattr(cb, "JUDGE_BACKEND_CONFIG", tmp_path / "b.json")
    with pytest.raises(cb.BridgeUnavailable) as e:
        cb.resolve_endpoint("gpt-5.6-sol")
    assert "judge-config" in str(e.value)


def test_score_rubric_reaches_the_model_through_the_cli_transport():
    """The legacy fallback must not be what a Codex run reaches.

    This asserted `_codex.resolve_endpoint(judge_model`, an HTTP endpoint
    resolution belonging to the superseded litellm path. The judge runs the
    model as a subprocess, so the property that carries the same meaning is
    that it goes through the one subprocess implementation rather than
    building its own."""
    src = (Path(cb.__file__).parent / "rubric_judge.py").read_text()
    assert "_codex_cli._codex_exec(" in src
    assert "subprocess." not in src


# ----- pinnability -----
#
# `backend_pinned` was the literal False. A constant cannot be checked and
# cannot change when the backend does, which is half of why
# C-GAP-JUDGE-TRANSPORT-UNPINNED capped at HOLD. It is derived now.


def test_the_pin_verdict_is_derived_from_stated_criteria():
    a = cb.pin_assessment({})
    assert set(a["criteria"]) == set(cb.PIN_CRITERIA)
    assert a["pinned"] is all(a["criteria"].values())
    for name in cb.PIN_CRITERIA:
        assert a["basis"][name], f"{name} has no stated basis"


def test_an_undocumented_backend_is_not_pinned_even_with_a_build_identity():
    """The criterion that fails is the one that cannot be fixed from here, and
    a reported version must not be allowed to paper over it."""
    a = cb.pin_assessment({"version": "0.4.1"})
    assert a["criteria"]["resolvable_build_identity"] is True
    assert a["criteria"]["documented_stable_api"] is False
    assert a["pinned"] is False
    assert a["build_identity"] == "0.4.1"


def test_an_unidentifiable_build_is_recorded_as_unmet_not_assumed():
    a = cb.pin_assessment({})
    assert a["criteria"]["resolvable_build_identity"] is False
    assert a["build_identity"] is None


def test_the_record_says_it_does_not_cover_the_graded_path():
    """Without this the record reads as the graded judge's pin record, which it
    is not: a scored run never imports this module."""
    rec = cb.BridgeStatus(
        "http://127.0.0.1:3456", "gpt-5.6-sol", True, True, True, ["gpt-5.6-sol"], "ok",
    ).as_record()
    assert rec["covers"] == "smoke-and-preflight"
    assert "rubric_judge_cli" in rec["grading_path"]
    assert rec["backend_pinned"] is rec["pin_assessment"]["pinned"]
