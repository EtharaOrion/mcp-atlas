"""Stage plumbing in scripts/run_task.sh.

Harbor itself is stubbed on PATH, so these cover what the script decides -- the
run_N a stage owns, the state it hands to the next stage, the runs it protects
from being wiped -- without building a container.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import mirror_harbor_package

REPO = Path(__file__).resolve().parent.parent.parent
RUN_TASK = REPO / "scripts" / "run_task.sh"

HARBOR_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$@" >> "$HARBOR_ARGS"
# The environment harbor's claude_code agent would read (and forward into the
# container). Recorded so provider-mode tests can assert on what reached harbor
# rather than on what run_task.sh printed.
if [ -n "${HARBOR_ENV:-}" ]; then env > "$HARBOR_ENV"; fi
mkdir -p "$JOB_DIR"
touch "$JOB_DIR/result.json"
exit 0
"""

BEDROCK_ARN = "arn:aws:bedrock:ap-south-1:123456789012:application-inference-profile/abc123xyz"
BEDROCK_TOKEN = "ABSKdGVzdC10b2tlbg=="   # base64 shape, trailing '=' like a real Bedrock API key


@pytest.fixture
def env(tmp_path):
    task = tmp_path / "tasks" / "alpha"
    task.mkdir(parents=True)
    (task / "task.toml").write_text('name = "acme/alpha"\nimage = "example/img:1"\n')

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "harbor"
    stub.write_text(HARBOR_STUB)
    stub.chmod(0o755)

    # Shadowing `harbor` on PATH also redirects patch_harbor.py, which run_task.sh
    # runs before dispatch and which resolves the harbor package relative to that
    # binary. Without a mirrored package it raises, run_task.sh aborts, and every
    # assertion below fails on an empty argv -- looking like a dispatch bug rather
    # than a missing fixture. See scripts/tests/conftest.py.
    if not mirror_harbor_package(tmp_path):
        pytest.skip("harbor is not installed; cannot mirror its package")

    class Env:
        root = tmp_path
        task_dir = task
        output = tmp_path / "output"
        harbor_args = tmp_path / "harbor_args.txt"
        harbor_env_file = tmp_path / "harbor_env.txt"

        def run(self, stage, **overrides):
            e = dict(os.environ)
            e.update({
                "PATH": f"{bin_dir}:{e['PATH']}",
                "OUTPUT_DIR": str(self.output),
                "JOB": "alpha",
                "JOB_DIR": str(self.output / "alpha"),
                "HARBOR_ARGS": str(self.harbor_args),
                "HARBOR_ENV": str(self.harbor_env_file),
            })
            e.update({k: str(v) for k, v in overrides.items()})
            return subprocess.run(
                [str(RUN_TASK), "--stage", stage, str(task)],
                capture_output=True, text=True, env=e, cwd=str(REPO), timeout=120)

        def state(self):
            return json.loads((self.output / "alpha" / ".run_state.json").read_text())

        def harbor_argv(self):
            return self.harbor_args.read_text().split("\n") if self.harbor_args.exists() else []

        def harbor_env(self):
            if not self.harbor_env_file.exists():
                return {}
            out = {}
            for line in self.harbor_env_file.read_text().splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    out[k] = v
            return out

    return Env()


def test_unknown_stage_is_rejected(env):
    r = env.run("nonsense")
    assert r.returncode == 2
    assert "unknown stage" in r.stderr


def test_missing_task_dir_is_rejected(tmp_path):
    r = subprocess.run([str(RUN_TASK), "--stage", "harbor", str(tmp_path / "nope")],
                       capture_output=True, text=True, cwd=str(REPO), timeout=60)
    assert r.returncode == 2
    assert "not a task dir" in r.stderr


def test_help_lists_the_stages():
    r = subprocess.run([str(RUN_TASK), "--help"], capture_output=True, text=True,
                       cwd=str(REPO), timeout=60)
    assert r.returncode == 0
    for stage in ("preflight", "harbor", "reshape", "finance"):
        assert stage in r.stdout


def test_harbor_stage_records_state_for_the_next_stage(env):
    r = env.run("harbor", RUN_OFFSET=2, MODEL="m1", AGENT="claude-code", N=1)
    assert r.returncode == 0, r.stderr
    state = env.state()
    assert state["run_offset"] == 2
    assert state["slug"] == "alpha" and state["job"] == "alpha"
    assert state["harbor_done"] == 1


def test_explicit_run_offset_beats_what_is_on_disk(env):
    (env.output / "alpha" / "trajectory" / "run_1").mkdir(parents=True)
    (env.output / "alpha" / "trajectory" / "run_2").mkdir(parents=True)
    env.run("harbor", RUN_OFFSET=0)
    assert env.state()["run_offset"] == 0


def test_offset_falls_back_to_counting_existing_runs(env):
    """A bare run_task.sh, with no driver deciding for it, still appends."""
    for n in (1, 2, 3):
        (env.output / "alpha" / "trajectory" / f"run_{n}").mkdir(parents=True)
    env.run("harbor")
    assert env.state()["run_offset"] == 3


def test_earlier_runs_are_stashed_outside_the_job_dir(env):
    """Harbor may clear output/<job>/ wholesale, stash included, if it lives there."""
    (env.output / "alpha" / "trajectory" / "run_1").mkdir(parents=True)
    (env.output / "alpha" / "trajectory" / "run_1" / "marker").write_text("keep me")
    env.run("harbor", RUN_OFFSET=1)
    stash = Path(env.state()["stash_dir"])
    assert stash == env.output / ".stash" / "alpha"
    assert (stash / "run_1" / "marker").read_text() == "keep me"
    assert env.output / "alpha" not in stash.parents


def test_harbor_argv_carries_the_job_and_attempt_count(env):
    env.run("harbor", RUN_OFFSET=0, MODEL="m1", N=1)
    argv = env.harbor_argv()
    assert "--job-name" in argv and "alpha" in argv
    assert "--n-attempts" in argv
    assert "--model" in argv and "m1" in argv


def test_oracle_agent_gets_no_model_flag(env):
    env.run("harbor", RUN_OFFSET=0, AGENT="oracle", MODEL="m1")
    assert "--model" not in env.harbor_argv()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

DOCKER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$DOCKER_CALLS"
exit 0
"""

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

BUNDLES = sorted(p for p in (REPO / "tasks").glob("*/environment/docker-compose.yaml")) \
    if (REPO / "tasks").is_dir() else []


# ------------------------------------------------------------ provider modes
# CC_MODE=bedrock is Claude Code on AWS Bedrock. run_task.sh calls nothing on
# AWS itself; it hands harbor the switches its claude_code agent keys Bedrock
# mode on (CLAUDE_CODE_USE_BEDROCK / AWS_BEARER_TOKEN_BEDROCK / AWS_REGION) and
# the Bedrock model id as --model. NETWORK_ISOLATION_OFF keeps these hermetic:
# the isolated path builds the egress-proxy image, which is docker's business,
# not this file's.


def _bedrock(env, **overrides):
    base = dict(
        CC_MODE="bedrock",
        AWS_BEARER_TOKEN_BEDROCK=BEDROCK_TOKEN,
        AWS_REGION="ap-south-1",
        BEDROCK_MODEL_ID=BEDROCK_ARN,
        MODEL="",                       # explicit-empty: the mode's default must win
        NETWORK_ISOLATION_OFF="1",
    )
    base.update(overrides)
    return env.run("harbor", **base)


def test_bedrock_mode_hands_harbor_the_bedrock_switches(env):
    r = _bedrock(env)
    argv = env.harbor_argv()
    assert argv, f"harbor was never reached:\n{r.stdout}\n{r.stderr}"
    assert argv[argv.index("--model") + 1] == BEDROCK_ARN, "BEDROCK_MODEL_ID must become --model"
    he = env.harbor_env()
    assert he.get("CLAUDE_CODE_USE_BEDROCK") == "1"
    assert he.get("AWS_BEARER_TOKEN_BEDROCK") == BEDROCK_TOKEN, "the bearer token must survive to harbor"
    assert he.get("AWS_REGION") == "ap-south-1"
    # A proxy URL here would send the Bedrock model id to api.anthropic.com.
    assert "ANTHROPIC_BASE_URL" not in he
    assert "[run_task] bedrock:" in r.stdout


def test_bedrock_model_override_beats_the_dotenv_default(env):
    _bedrock(env, MODEL="us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    argv = env.harbor_argv()
    assert argv[argv.index("--model") + 1] == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_bedrock_token_is_dropped_outside_bedrock_mode(env):
    """Either variable alone flips harbor's agent into Bedrock mode
    (claude_code.py::_is_bedrock_mode). A token left in the shell must not
    reroute an Anthropic run."""
    r = env.run("harbor", AWS_BEARER_TOKEN_BEDROCK=BEDROCK_TOKEN,
                CLAUDE_CODE_USE_BEDROCK="1", NETWORK_ISOLATION_OFF="1")
    assert env.harbor_argv(), f"harbor was never reached:\n{r.stdout}\n{r.stderr}"
    he = env.harbor_env()
    assert "AWS_BEARER_TOKEN_BEDROCK" not in he
    assert "CLAUDE_CODE_USE_BEDROCK" not in he


def test_bedrock_mode_without_a_credential_refuses_before_harbor(env):
    r = _bedrock(env, AWS_BEARER_TOKEN_BEDROCK="", AWS_ACCESS_KEY_ID="", AWS_SECRET_ACCESS_KEY="")
    assert r.returncode != 0
    assert "no AWS credential" in r.stderr
    assert not env.harbor_argv(), "a run with no credential must not start a paid trial"


def test_bedrock_mode_accepts_sigv4_keys(env):
    r = _bedrock(env, AWS_BEARER_TOKEN_BEDROCK="", AWS_ACCESS_KEY_ID="AKIATEST",
                 AWS_SECRET_ACCESS_KEY="secret")
    assert env.harbor_argv(), f"harbor was never reached:\n{r.stdout}\n{r.stderr}"
    he = env.harbor_env()
    assert he.get("AWS_ACCESS_KEY_ID") == "AKIATEST"
    assert he.get("CLAUDE_CODE_USE_BEDROCK") == "1"


def test_bedrock_mode_without_a_region_refuses(env):
    r = _bedrock(env, AWS_REGION="")
    assert r.returncode != 0
    assert "AWS_REGION" in r.stderr
    assert not env.harbor_argv()


def test_bedrock_mode_without_a_model_refuses(env):
    r = _bedrock(env, BEDROCK_MODEL_ID="")
    assert r.returncode != 0
    assert "BEDROCK_MODEL_ID" in r.stderr
    assert not env.harbor_argv()
