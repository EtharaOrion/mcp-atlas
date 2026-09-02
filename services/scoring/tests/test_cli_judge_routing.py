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


def test_the_cli_default_model_is_the_codex_model():
    assert 'os.getenv("JUDGE_MODEL", "gpt-5.6-sol")' in Path(cli.__file__).read_text()
