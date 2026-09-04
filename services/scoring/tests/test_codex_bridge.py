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
    assert cb.provider_route("gpt-5.6-luna") == "anthropic/gpt-5.6-luna"


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
    # Read the source rather than importing it: rubric_judge pulls in litellm,
    # and skipping this when that is absent would drop the check entirely.
    judge = (Path(cb.__file__).parent / "rubric_judge.py").read_text()
    assert '_codex.resolve("EVAL_LLM_BASE_URL"' in judge
    assert "_codex.api_key(" in judge
    assert 'os.environ.get("EVAL_LLM_BASE_URL")' not in judge


def test_judge_omits_response_format_on_the_anthropic_path():
    """`response_format` is an OpenAI chat/completions parameter with no
    Anthropic Messages equivalent, so sending it there is rejected rather than
    ignored. _extract_json recovers the object instead."""
    src = (Path(cb.__file__).parent / "rubric_judge.py").read_text()
    assert 'if not model_for_call.startswith("anthropic/"):' in src
    assert '"response_format"' in src


def test_no_sonnet_default_survives_anywhere_in_the_judge_path():
    """The judge grades on gpt-5.6-sol and nothing else."""
    here = Path(cb.__file__).parent
    for name in ("rubric_judge.py", "rubric_judge_cli.py", "codex_bridge.py"):
        assert "claude-sonnet-4-6" not in (here / name).read_text(), name


def test_judge_default_model_is_the_codex_model():
    import importlib
    rj = importlib.import_module("services.scoring.rubric_judge")
    assert rj._DEFAULT_JUDGE_MODEL == "gpt-5.6-sol"
    assert rj._provider_route is cb.provider_route


# ----- the mounted config channel -----
#
# The bundle's docker-compose mounts services/scoring read-only at
# /harness/scoring, so a file beside codex_bridge.py reaches the judge running
# inside the task container. That is the only channel into the verifier that
# does not require editing a shipped task.toml, and editing one would change
# the bundle digest pinned in memory/crucible_view.yaml task_artifact_hashes.


def test_config_is_read_from_beside_the_module(monkeypatch, tmp_path):
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


def test_api_key_falls_back_to_the_mounted_config(monkeypatch, tmp_path):
    """The container has no CB_API_KEY exported; the mounted file carries it."""
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


def test_score_rubric_uses_the_guarded_endpoint():
    """The legacy fallback must not be what a Codex run reaches."""
    src = (Path(cb.__file__).parent / "rubric_judge.py").read_text()
    assert "_codex.resolve_endpoint(judge_model" in src
