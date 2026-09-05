#!/usr/bin/env python3
"""Prove Harbor can enforce this task's network policy BEFORE anything is spent.

    scripts/preflight_network.py tasks/<task> [--env-type docker]

Exit 0 = go. Exit 2 = a blocker, named, with the fix.

WHY THIS EXISTS

Harbor validates the network policy inside ``Trial.__init__`` -- which runs
*after* ``Trial.create()`` has already made the trial directory, and after the
environment image has been built. A policy Harbor cannot enforce therefore does
not fail early and loudly; it fails late, leaving a trial directory with no
``config.json``, and every stage downstream treats that as "a run that produced
nothing" rather than "a run that never started":

  scripts/harbor_to_output.py:1129 selects trial dirs with
      ``(p / "config.json").exists()``
  so an aborted trial is silently SKIPPED, ``written`` comes back empty, and
  reshape exits 0 having done nothing. No traceback, no error -- just a task
  directory that quietly never gains a Run_N.

The three failures this catches have all already happened to this bundle set:

  agent phase override != [environment] baseline   Trial.__init__ raises; the
                                                   docker provider declares
                                                   dynamic_network_policy=False
  network_mode = "allowlist" on docker             docker declares
                                                   network_allowlist=False
  allowed_hosts beside a non-allowlist mode        pydantic rejects at load

The rule this encodes, as in deku's harness/preflight.sh: check the path the
RUNNER takes, not one that resembles it. Every policy question below is answered
by importing Harbor's OWN resolver and the REAL provider capability flags, so
this file cannot drift from what `harbor run` will decide.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

FAIL = 0


def ok(m: str) -> None:
    print(f"  \033[32mok\033[0m    {m}")


def bad(m: str, f: str | None = None) -> None:
    global FAIL
    FAIL = 1
    print(f"  \033[31mFAIL\033[0m  {m}")
    if f:
        print(f"        -> {f}")


def warn(m: str, f: str | None = None) -> None:
    print(f"  \033[33mwarn\033[0m  {m}")
    if f:
        print(f"        -> {f}")


def declared_policy() -> tuple[str, str]:
    """The repo's single declared baseline, read from the one place that sets it.

    adapters/mcp_atlas/adapter.py::DEFAULT_NETWORK_MODE is what the generator
    writes into every bundle and what adapters/mcp_atlas/tests/test_adapter.py
    ::test_network_mode_is_explicit asserts. Importing it rather than repeating
    the string is the whole point: a preflight that hardcoded "public" would
    become a SECOND rule, free to disagree with the first.
    """
    sys.path.insert(0, str(REPO / "adapters" / "mcp_atlas"))
    try:
        import adapter  # type: ignore
        return adapter.DEFAULT_NETWORK_MODE, "adapters/mcp_atlas/adapter.py::DEFAULT_NETWORK_MODE"
    except Exception:
        return "public", "fallback (adapter.py not importable)"


class UnknownProvider(Exception):
    """--env-type named something harbor has no provider for."""


def provider_capabilities(env_type: str):
    """The REAL capability flags of the provider `harbor run` will instantiate.

    Resolved through Harbor's own registry, not a local table, so a provider
    that gains allowlist or dynamic-switch support is picked up here the moment
    Harbor ships it.
    """
    from harbor.environments.factory import _ENVIRONMENT_REGISTRY
    from harbor.models.environment_type import EnvironmentType

    # A name Harbor does not know is a CALLER error -- a typo in --env-type would
    # otherwise skip every enforceability check below and still exit 0, which is
    # the precise failure this file exists to prevent. Distinguished from the
    # case below on purpose.
    try:
        entry = _ENVIRONMENT_REGISTRY[EnvironmentType(env_type)]
    except (KeyError, ValueError):
        known = sorted(e.value for e in EnvironmentType)
        raise UnknownProvider(f"{env_type!r} is not a harbor environment type "
                              f"(known: {', '.join(known)})") from None

    cls = getattr(importlib.import_module(entry.module), entry.class_name)
    caps = cls.__dict__.get("capabilities", cls.capabilities)
    if not isinstance(caps, property):
        return caps
    # Some providers (modal) compute capabilities from instance state at
    # construction, so there is nothing to read statically. That is a genuine
    # limitation, not a caller mistake -- it degrades to a warn, not a FAIL.
    return caps.fget(None)


def sidecar_hosts(task_dir: Path, raw: dict) -> list[str]:
    """MCP server hostnames the agent must reach over the compose network.

    These are the reason `no-network` is not merely unenforceable here but
    wrong: harbor/environments/docker/docker-compose-no-network.yaml sets
    `network_mode: none` on the `main` service, which detaches it from the
    compose bridge too. The agent would come up with zero tools and grade 0.
    """
    hosts = []
    for srv in raw.get("environment", {}).get("mcp_servers", []) or []:
        url = srv.get("url") or ""
        if "://" in url:
            host = url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
            if host not in ("localhost", "127.0.0.1"):
                hosts.append(f"{srv.get('name', '?')} -> {host}")
    return hosts


def check(task_dir: Path, env_type: str) -> None:
    toml_path = task_dir / "task.toml"
    if not toml_path.is_file():
        bad(f"no task.toml in {task_dir}")
        return
    try:
        raw = tomllib.loads(toml_path.read_text())
    except Exception as exc:
        bad(f"task.toml does not parse: {exc}")
        return

    want, want_src = declared_policy()

    # ---------------------------------------------------------- unset default
    # [environment].network_mode has a DEFAULT of public in Harbor
    # (BaselineNetworkPolicyConfig). Leaving it unset is not neutral: the
    # default is what decides whether an explicit [agent]/[verifier] override
    # counts as a phase switch, i.e. whether the trial aborts.
    env_raw = raw.get("environment", {}) or {}
    baseline_declared = env_raw.get("network_mode")
    overrides = {
        role: (raw.get(role, {}) or {}).get("network_mode")
        for role in ("agent", "verifier")
    }
    explicit_overrides = {r: v for r, v in overrides.items() if v is not None}

    if baseline_declared is None:
        msg = "[environment].network_mode is unset -- harbor defaults it to 'public'"
        if explicit_overrides:
            bad(msg + f", and {sorted(explicit_overrides)} override(s) are measured against it",
                f'set network_mode = "{want}" in [environment] explicitly ({want_src})')
        else:
            warn(msg, f'set network_mode = "{want}" in [environment] explicitly ({want_src})')
    elif baseline_declared != want:
        bad(f'[environment].network_mode = "{baseline_declared}" but this repo declares "{want}"',
            f'either set network_mode = "{want}" in [environment], or change {want_src} '
            f'(they must not disagree)')
    else:
        ok(f'[environment].network_mode = "{baseline_declared}" (matches {want_src})')

    # ------------------------------------------------- allowlist where ignored
    # Two distinct traps. Harbor's pydantic rejects allowed_hosts beside a
    # non-allowlist mode outright; harbor/trial/network_policy.py
    # ::merge_extra_allowlists merely WARNS and drops run-time extra hosts
    # against a public policy. Neither is visible until a trial is constructed.
    for role, section in (("environment", env_raw),
                          ("agent", raw.get("agent", {}) or {}),
                          ("verifier", raw.get("verifier", {}) or {})):
        hosts = section.get("allowed_hosts")
        if not hosts:
            continue
        mode = section.get("network_mode")
        if mode is None:
            bad(f"[{role}].allowed_hosts is set with no [{role}].network_mode",
                f"harbor raises \"allowed_hosts is only valid when "
                f"network_mode='allowlist'\"; drop allowed_hosts or set the mode")
        elif mode != "allowlist":
            bad(f'[{role}].allowed_hosts is set alongside network_mode = "{mode}"',
                "harbor raises \"allowed_hosts is only valid when "
                "network_mode='allowlist'\"; remove them TOGETHER, not one of the two")
        else:
            ok(f"[{role}].allowed_hosts is paired with allowlist mode")

    # ------------------------------------------------ ask harbor, not ourselves
    try:
        from harbor.models.task.config import TaskConfig
        from harbor.models.trial.config import AgentConfig, EnvironmentConfig
        from harbor.models.task.verifier_mode import (
            resolve_step_verifier_mode,
            resolve_task_verifier_mode,
        )
        from harbor.trial.network_policy import resolve_trial_network_plan
        from harbor.trial.trial import Trial
        from harbor.environments.base import BaseEnvironment
    except Exception:
        warn("harbor is not importable from this interpreter -- policy enforceability "
             "was NOT checked",
             "run this under harbor's python: "
             "$(dirname $(readlink -f $(command -v harbor)))/python")
        return

    try:
        cfg = TaskConfig.model_validate(raw)
    except Exception as exc:
        bad(f"harbor rejects this task.toml: {str(exc).splitlines()[0]}",
            "harbor raises this in Trial.__init__, AFTER the image is built")
        return

    try:
        caps = provider_capabilities(env_type)
    except UnknownProvider as exc:
        bad(f"{exc}", "pass a real provider to --env-type; nothing below was checked")
        return
    except Exception as exc:
        warn(f"{env_type} computes its capabilities at construction "
             f"({type(exc).__name__}: {exc}) -- policy enforceability was NOT checked",
             "this provider cannot be inspected statically; run it to find out")
        return

    # Mirror Trial._validate_network_policy_modes EXACTLY: a task with [[steps]]
    # gets one plan per step, each with its own verifier mode, and Harbor
    # validates every one. Checking only the stepless plan would be a check that
    # merely resembles the runner's path -- the failure this whole file exists to
    # prevent.
    if cfg.steps:
        plans = [
            (f"Step {step.name!r}",
             resolve_trial_network_plan(
                 cfg, AgentConfig(name="claude-code"), EnvironmentConfig(), step,
                 verifier_mode=resolve_step_verifier_mode(cfg, step)))
            for step in cfg.steps
        ]
    else:
        plans = [
            ("[agent]",
             resolve_trial_network_plan(
                 cfg, AgentConfig(name="claude-code"), EnvironmentConfig(), None,
                 verifier_mode=resolve_task_verifier_mode(cfg)))
        ]

    # ------------------------------------- what the kernel here can enforce
    class _Probe:
        """Capability-only stand-in: BaseEnvironment.validate_network_policy_support
        reads nothing but `capabilities` and `type()`, so this exercises the real
        method rather than a paraphrase of it."""
        capabilities = caps
        _network_policy = None

        @staticmethod
        def type():
            return env_type

        def validate_network_policy_support(self, policy=None):
            return BaseEnvironment.validate_network_policy_support(self, policy)

    probe = _Probe()
    shim = type("_Shim", (), {
        "agent_environment": probe,
        "_validate_network_plan": Trial._validate_network_plan,
        "_validate_dynamic_phase_switch": Trial._validate_dynamic_phase_switch,
    })()
    hosts = sidecar_hosts(task_dir, raw)

    for plan_label, plan in plans:
        pfx = "" if plan_label == "[agent]" else f"{plan_label}: "

        # ------------------------------- what the kernel here can enforce
        for label, policy in (("[environment] baseline", plan.agent_env_baseline),
                              ("[agent] phase", plan.agent_phase),
                              ("[verifier] phase", plan.verifier_phase)):
            if policy is None:
                continue
            try:
                probe.validate_network_policy_support(policy)
                ok(f'{pfx}{label} network_mode = "{policy.network_mode.value}" is '
                   f"enforceable by the {env_type} provider")
            except Exception as exc:
                bad(f"{pfx}{label}: {exc}",
                    f"the {env_type} provider on this host cannot enforce "
                    f'"{policy.network_mode.value}" '
                    f"(network_allowlist={caps.network_allowlist}, "
                    f"disable_internet={caps.disable_internet})")

        # ------------------------------------ the dynamic-switch blocker
        # Harbor's OWN validator, bound to the real capability flags. This is
        # the check that fires in Trial.__init__, after the build is paid for.
        try:
            shim._validate_network_plan(plan, label=plan_label)
            ok(f"{pfx}harbor's own Trial network validation passes")
        except Exception as exc:
            bad(f"harbor would abort the trial: {exc}",
                f'[environment].network_mode = '
                f'"{plan.agent_env_baseline.network_mode.value}" but the agent phase '
                f'resolves to "{plan.agent_phase.network_mode.value}"; the {env_type} '
                f"provider declares dynamic_network_policy={caps.dynamic_network_policy}, "
                f"so the two must be equal. Make them agree.")

        # -------------------------- the path the AGENT actually takes
        if hosts and plan.agent_phase.network_mode.value == "no-network":
            bad(f"{pfx}agent phase is 'no-network' but the task declares compose-sidecar "
                "MCP servers: " + "; ".join(hosts),
                "no-network sets `network_mode: none` on the main service "
                "(harbor/environments/docker/docker-compose-no-network.yaml), which "
                "detaches it from the compose bridge too -- the agent would start with "
                "ZERO tools")
        elif hosts:
            ok(f"{pfx}{len(hosts)} MCP sidecar host(s) reachable under "
               f"'{plan.agent_phase.network_mode.value}'")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("task_dir", type=Path)
    ap.add_argument("--env-type", default="docker",
                    help="harbor environment provider the run will use (default: docker)")
    a = ap.parse_args(argv)

    if not a.task_dir.is_dir():
        print(f"  \033[31mFAIL\033[0m  task directory not found: {a.task_dir}")
        return 2

    print(f"== network policy: {a.task_dir} ({a.env_type}) ==")
    check(a.task_dir, a.env_type)
    if FAIL:
        print("\n  blocked: fix the above before spending an agent phase.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
