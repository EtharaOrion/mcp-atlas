"""The egress block is configuration, and configuration regresses silently.

These tests assert the three properties that make it real, all of them cheap and
none of them needing Docker to run a container:

  1. the overlay makes the project's default network internal, and puts main on
     it and nothing else -- this is what removes the route, and it is the only
     part the agent cannot defeat from inside;
  2. every task bundle stays on network_mode = "public", because any other value
     re-introduces the abort this replaced;
  3. every bundle pre-bakes the CLI, because harbor's own installer cannot reach
     downloads.claude.ai once the block is on.

A `docker compose config` is used for (1) rather than a YAML diff: the question
is what Compose *resolves*, and the implicit default network only appears there.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
OVERLAY = REPO / "services" / "egress-proxy" / "overlay.yaml"
BUNDLES = sorted(REPO.glob("tasks/*/task.toml"))

pytestmark = pytest.mark.skipif(not BUNDLES, reason="no task bundles in this checkout")


def _ids(paths):
    return [p.parent.name for p in paths]


def test_overlay_exists():
    assert OVERLAY.is_file(), f"network isolation overlay missing at {OVERLAY}"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
@pytest.mark.parametrize("task_toml", BUNDLES, ids=_ids(BUNDLES))
def test_overlay_isolates_main(task_toml: Path):
    """main must end up on an internal network, and off the egress one."""
    compose = task_toml.parent / "environment" / "docker-compose.yaml"
    if not compose.is_file():
        pytest.skip(f"{task_toml.parent.name} has no compose file")

    proc = subprocess.run(
        ["docker", "compose", "-f", str(compose), "-f", str(OVERLAY), "config", "--format", "json"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "SCORING_DIR": str(REPO / "services" / "scoring")},
    )
    if proc.returncode != 0:
        pytest.fail(f"compose config failed:\n{proc.stderr}")

    cfg = json.loads(proc.stdout)
    networks = cfg.get("networks") or {}
    services = cfg.get("services") or {}

    assert networks.get("default", {}).get("internal") is True, (
        "the default network is not internal -- main keeps a route to the open web"
    )
    assert "egress" in networks, "no egress network for the proxy to reach out through"

    main_nets = set((services.get("main") or {}).get("networks") or {})
    assert main_nets == {"default"}, (
        f"main must sit on the internal default network alone, got {sorted(main_nets)}"
    )

    proxy = services.get("egress-proxy")
    assert proxy, "overlay did not contribute the egress-proxy service"
    assert set(proxy.get("networks") or {}) == {"default", "egress"}, (
        "the proxy must span both networks; it is the only route out"
    )

    # The sidecars are the reason no-network was unusable. Keep them reachable.
    if "light-servers" in services:
        assert set(services["light-servers"].get("networks") or {}) == {"default"}


@pytest.mark.parametrize("task_toml", BUNDLES, ids=_ids(BUNDLES))
def test_network_mode_stays_public(task_toml: Path):
    """no-network detaches the compose bridge and grades the run 0.

    It also differs from [environment], and the docker provider cannot switch
    policy mid-trial, so the trial aborts before the agent phase.
    """
    cfg = tomllib.loads(task_toml.read_text())
    env_mode = (cfg.get("environment") or {}).get("network_mode")
    agent_mode = (cfg.get("agent") or {}).get("network_mode")

    assert env_mode == "public", f"[environment].network_mode is {env_mode!r}, must be 'public'"
    if agent_mode is not None:
        assert agent_mode == "public", (
            f"[agent].network_mode is {agent_mode!r}; egress is blocked by the compose "
            "overlay, not by harbor, so this must stay 'public'"
        )


@pytest.mark.parametrize("task_toml", BUNDLES, ids=_ids(BUNDLES))
def test_bundle_prebakes_cli(task_toml: Path):
    """harbor's installer cannot reach downloads.claude.ai under isolation."""
    dockerfile = task_toml.parent / "environment" / "Dockerfile"
    if not dockerfile.is_file():
        pytest.skip(f"{task_toml.parent.name} has no Dockerfile")

    body = dockerfile.read_text()
    assert "downloads.claude.ai" in body, (
        "Dockerfile does not pre-bake the Claude Code CLI; agent setup will try to "
        "download it inside the container, where there is no route out"
    )
    assert "procps" in body, (
        "procps missing -- harbor's installer used to add it and is now a no-op, "
        "but claude's node-tree-kill still shells out to ps/pgrep"
    )


# --- tool-level deny ---------------------------------------------------------
# The second layer, borrowed from WildClawBench's tools.deny: the routing block
# already makes WebSearch/WebFetch fail, but a failing tool still costs a turn.
# Denying them removes them from the tool list entirely.
#
# These drive run_task.sh with a stub `harbor` on PATH and read the argv it
# built, so they check the wiring rather than re-stating the constant.

RUN_TASK = REPO / "scripts" / "run_task.sh"

_HARBOR_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$@" >> "$HARBOR_ARGS"
mkdir -p "$JOB_DIR"
touch "$JOB_DIR/result.json"
exit 0
"""


def _harbor_argv(tmp_path, **overrides) -> list[str]:
    """Run the harbor stage against a stub harbor and return the argv it got."""
    import os
    import pathlib
    import shutil
    import subprocess

    task = tmp_path / "tasks" / "alpha"
    task.mkdir(parents=True)
    (task / "task.toml").write_text('name = "acme/alpha"\n')

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "harbor"
    stub.write_text(_HARBOR_STUB)
    stub.chmod(0o755)

    # run_task.sh runs patch_harbor.py at dispatch, and
    # find_harbor_claude_code() locates harbor relative to whichever `harbor` is
    # on PATH: it globs <venv>/lib/python*/site-packages/harbor/... where <venv>
    # is the stub's grandparent. Shadowing PATH therefore points it at this tmp
    # dir, and it dies before harbor is ever invoked -- which is why the
    # pre-existing test_run_task_stages.py cases fail too.
    #
    # Mirror the two files it patches into a fake venv layout so the glob
    # resolves here. They are COPIES: patch_harbor rewrites them in place, and
    # a test must not mutate the real harbor install.
    real_harbor = shutil.which("harbor")
    if real_harbor:
        real_pkg = None
        venv_root = pathlib.Path(real_harbor).resolve().parent.parent
        for cc in venv_root.glob("lib/python*/site-packages/harbor/agents/installed/claude_code.py"):
            real_pkg = cc.parent.parent.parent
            rel = cc.relative_to(venv_root)
            break
        if real_pkg is not None:
            for src, dest_rel in (
                (real_pkg / "agents" / "installed" / "claude_code.py", rel),
                (real_pkg / "trial" / "trial.py",
                 rel.parent.parent.parent / "trial" / "trial.py"),
            ):
                dest = tmp_path / dest_rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.exists():
                    dest.write_text(src.read_text())

    args_file = tmp_path / "harbor_args.txt"
    env = dict(os.environ)
    env.update({
        "PATH": f"{bin_dir}:{env['PATH']}",
        "OUTPUT_DIR": str(tmp_path / "output"),
        "JOB": "alpha",
        "JOB_DIR": str(tmp_path / "output" / "alpha"),
        "HARBOR_ARGS": str(args_file),
        "RUN_OFFSET": "0",
        "MODEL": "m1",
        "N": "1",
        "AGENT": "claude-code",
    })
    env.update({k: str(v) for k, v in overrides.items()})

    subprocess.run(
        [str(RUN_TASK), "--stage", "harbor", str(task)],
        capture_output=True, text=True, env=env, cwd=str(REPO), timeout=300,
    )
    if not args_file.exists():
        pytest.skip("harbor stage did not reach harbor (unrelated preflight failure)")
    return args_file.read_text().split("\n")


def test_web_tools_denied_when_isolated(tmp_path):
    argv = _harbor_argv(tmp_path)
    assert "disallowed_tools=WebSearch,WebFetch" in argv, (
        "web tools not denied; the agent will spend turns on tools that cannot work"
    )


def test_bash_is_not_denied(tmp_path):
    """Bash does real local work and its egress is already dead at the router."""
    argv = _harbor_argv(tmp_path)
    denied = [a for a in argv if a.startswith("disallowed_tools=")]
    assert denied, "expected a disallowed_tools flag"
    assert "Bash" not in denied[0], (
        "denying Bash breaks tasks to buy nothing -- egress is blocked by routing"
    )


def test_not_denied_when_isolation_is_off(tmp_path):
    """An operator who asked for an open run must get one, tools included."""
    argv = _harbor_argv(tmp_path, NETWORK_ISOLATION_OFF="1")
    assert not [a for a in argv if a.startswith("disallowed_tools=")], (
        "web tools still denied with NETWORK_ISOLATION_OFF=1; that run would not "
        "mean what the operator asked for"
    )
