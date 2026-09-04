"""The rubric judge reaches Codex through the local CLI, and nothing else.

This file used to test `_point_sdk_at_the_bridge` and then the codex-bridge
HTTP preflight. Both transports are gone: the judge now shells out to
`codex exec`, so preflight is the CLI's own `codex login status` and there is
no base URL, key, or server left to misconfigure.

What remains is worth asserting, because the absence of a thing is easy to
regress into: the judge must refuse a non-Codex model rather than quietly
finding some other way to grade, and it must fail before grading rather than
per-criterion, since rubric_judge_cli writes a score file from whatever it gets
back.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

cli = pytest.importorskip("services.scoring.rubric_judge_cli")


def test_the_claude_transport_is_gone():
    """No Agent SDK, no output-schema contract, no SDK usage walker."""
    src = Path(cli.__file__).read_text()
    for gone in ("ClaudeAgentOptions", "ClaudeSDKClient", "structured_output"):
        assert gone not in src, gone
    for attr in ("_OUTPUT_SCHEMA", "_record_usage", "_point_sdk_at_the_bridge"):
        assert not hasattr(cli, attr), attr


def test_no_claude_credential_juggling_remains():
    """The direct transport carries its key on the request, so none of the
    `claude` CLI's credential precedence is this module's concern any more."""
    src = Path(cli.__file__).read_text()
    for gone in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        assert f'os.environ["{gone}"]' not in src, gone


def test_a_non_codex_model_is_refused():
    import asyncio
    with pytest.raises(cli.JudgeResponseError) as e:
        asyncio.run(cli._run_judge([], "t", "f", "claude-sonnet-4-6"))
    assert "gpt-5.6-sol" in str(e.value)


def test_preflight_passes_when_codex_is_logged_in(monkeypatch):
    monkeypatch.setattr(cli, "_codex_credential_error", lambda: "")
    assert cli._preflight("gpt-5.6-sol") is None


def test_preflight_reports_a_missing_cli(monkeypatch):
    """No `codex` on PATH must be caught before grading, not per-criterion."""
    monkeypatch.setattr(cli, "_codex_cli", lambda: "")
    reason = cli._preflight("gpt-5.6-sol")
    assert reason is not None and "codex" in reason


def test_preflight_asks_the_cli_itself(monkeypatch):
    """`codex login status` is the check — no credential store is read."""
    monkeypatch.setattr(cli, "_codex_cli", lambda: "/usr/local/bin/codex")
    seen: dict = {}

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "Not logged in"

    def fake(argv, capture_output=None, text=None, timeout=None):
        seen["argv"] = argv
        return _Proc()

    monkeypatch.setattr(cli.subprocess, "run", fake)
    reason = cli._preflight("gpt-5.6-sol")
    assert seen["argv"] == ["/usr/local/bin/codex", "login", "status"]
    assert reason is not None and "codex login" in reason


def test_preflight_ignores_a_non_codex_model(monkeypatch):
    """The CLI is not consulted there; _run_judge does the refusing."""
    monkeypatch.setattr(cli, "_codex_cli", lambda: "")
    assert cli._preflight("claude-sonnet-4-6") is None


def test_the_cli_default_model_is_the_codex_model(monkeypatch):
    """On a host with codex installed, the pinned Codex grader still wins.

    Was a source-text assertion on the literal argparse default. The default is
    now resolved at runtime, because tests/test.sh invokes this CLI with no
    --model and the task container has no codex binary -- so a fixed default
    meant the bundle rubric channel could never be graded at all. Asserting the
    behaviour instead of the source keeps the guarantee that mattered.
    """
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.setattr(cli, "_codex_cli", lambda: "/usr/local/bin/codex")
    assert cli._default_judge_model() == cli.CODEX_MODELS[0]


def test_an_explicit_judge_model_is_never_overridden(monkeypatch):
    """A pinned grader is a benchmark property; resolution must not touch it."""
    monkeypatch.setenv("JUDGE_MODEL", "gpt-5.6-sol")
    monkeypatch.setattr(cli, "_codex_cli", lambda: "")
    monkeypatch.setattr(cli, "_claude_cli", lambda: "/root/.local/bin/claude")
    assert cli._default_judge_model() == "gpt-5.6-sol"


def test_container_without_codex_falls_back_to_claude(monkeypatch):
    """The case this transport exists for: the task container."""
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.setattr(cli, "_codex_cli", lambda: "")
    monkeypatch.setattr(cli, "_claude_cli", lambda: "/root/.local/bin/claude")
    assert cli._default_judge_model() == cli.CLAUDE_MODELS[0]


def test_neither_cli_keeps_the_codex_default(monkeypatch):
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.setattr(cli, "_codex_cli", lambda: "")
    monkeypatch.setattr(cli, "_claude_cli", lambda: "")
    assert cli._default_judge_model() == cli.CODEX_MODELS[0]


def test_claude_preflight_requires_a_credential(monkeypatch):
    monkeypatch.setattr(cli, "_claude_cli", lambda: "/root/.local/bin/claude")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reason = cli._preflight("claude-sonnet-4-5")
    assert reason is not None and "CLAUDE_CODE_OAUTH_TOKEN" in reason
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    assert cli._preflight("claude-sonnet-4-5") is None


def test_claude_preflight_reports_a_missing_cli(monkeypatch):
    monkeypatch.setattr(cli, "_claude_cli", lambda: "")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    reason = cli._preflight("claude-sonnet-4-5")
    assert reason is not None and "claude CLI not found" in reason


# ----- the graded path's own pin record -----
#
# C-GAP-JUDGE-TRANSPORT-UNPINNED was opened against codex_bridge.py. Fixing the
# record there alone would have left the transport that actually grades with no
# pin determination at all, so this path states its own -- and the two
# transports genuinely differ, which is what makes the determination worth
# recording rather than a blanket pessimistic constant.


def test_the_codex_transport_is_not_pinnable(monkeypatch):
    """Same undocumented ChatGPT-authenticated backend the bridge fronts.
    Reaching it by subprocess instead of HTTP does not document it."""
    monkeypatch.setattr(cli, "_codex_cli", lambda: "/usr/local/bin/codex")
    monkeypatch.setattr(cli, "_cli_version", lambda c, timeout=10.0: "codex-cli 0.152.1")
    r = cli.pin_record(cli.CODEX_MODELS[0])
    assert r["transport"] == "codex-cli"
    assert r["criteria"]["resolvable_build_identity"] is True
    assert r["criteria"]["documented_stable_api"] is False
    assert r["pinned"] is False


def test_the_claude_transport_is_pinnable(monkeypatch):
    """The one that grades inside the task container. Published versioned API,
    concrete model id -- so the run that produces a score has a pinnable judge,
    which is precisely what the gap said could not be established."""
    monkeypatch.setattr(cli, "_claude_cli", lambda: "/root/.local/bin/claude")
    monkeypatch.setattr(cli, "_cli_version", lambda c, timeout=10.0: "2.1.228 (Claude Code)")
    r = cli.pin_record(cli.CLAUDE_MODELS[0])
    assert r["transport"] == "claude-code-cli"
    assert r["pinned"] is True
    assert r["cli_version"] == "2.1.228 (Claude Code)"


def test_an_unreadable_version_fails_the_criterion_rather_than_passing_it(monkeypatch):
    """A build identity that could not be read is unestablished, not satisfied."""
    monkeypatch.setattr(cli, "_claude_cli", lambda: "/root/.local/bin/claude")
    monkeypatch.setattr(cli, "_cli_version", lambda c, timeout=10.0: None)
    r = cli.pin_record(cli.CLAUDE_MODELS[0])
    assert r["criteria"]["resolvable_build_identity"] is False
    assert r["pinned"] is False


def test_an_unknown_model_is_not_quietly_pinned():
    r = cli.pin_record("some-other-model")
    assert r["transport"] == "unknown"
    assert r["pinned"] is False


def test_the_pin_criteria_match_the_bridge_module():
    """One predicate across both records, so the two are comparable. Divergent
    criteria would let a transport look pinned only because it was judged by a
    weaker rule."""
    import importlib

    cb = importlib.import_module("services.scoring.codex_bridge")
    assert set(cli.pin_record(cli.CODEX_MODELS[0])["criteria"]) == set(cb.PIN_CRITERIA)


def test_a_version_probe_that_explodes_does_not_stop_grading(monkeypatch):
    """Provenance is worth recording; it is not worth failing a run over."""
    monkeypatch.setattr(cli, "_claude_cli", lambda: "/nonexistent/claude")
    assert cli._cli_version("/nonexistent/claude") is None
    assert cli.pin_record(cli.CLAUDE_MODELS[0])["pinned"] is False
