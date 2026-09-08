#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ANCHOR = '            format="--permission-mode={value}",\n        ),'
PATCH = """
        CliFlag(
            "thinking",
            cli="--thinking",
            type="str",
        ),
        CliFlag(
            "thinking_display",
            cli="--thinking-display",
            type="str",
        ),"""
ALREADY_PATCHED_MARKER = '"thinking_display"'


ANCHOR_ARGMAX_1 = "        run_env = {**env, instruction_env_var: instruction}"
REPLACEMENT_ARGMAX_1 = """        import base64 as _base64
        _instr_id = uuid.uuid4().hex
        _instr_file = f"/tmp/harbor_instruction_{_instr_id}"
        _instr_b64 = _base64.b64encode(instruction.encode("utf-8")).decode("ascii")
        _chunks = [_instr_b64[i:i+4000] for i in range(0, len(_instr_b64), 4000)]
        _wparts = (
            [f"> {_instr_file}.b64"]
            + [f'printf "%s" {shlex.quote(c)} >> {_instr_file}.b64' for c in _chunks]
            + [f"base64 -d {_instr_file}.b64 > {_instr_file} && rm -f {_instr_file}.b64"]
        )
        await self.exec_as_agent(
            environment,
            command=" && ".join(_wparts),
            env=env,
        )

        run_env = {**env}"""

ANCHOR_ARGMAX_2 = """\
                f'{instruction_shell_var}="${instruction_env_var}"; '
                f"unset {instruction_env_var}; "
                f'printf "%s" "${instruction_shell_var}" | '"""
REPLACEMENT_ARGMAX_2 = "                f'cat {_instr_file} | '"

ANCHOR_ARGMAX_3 = '                f"/logs/agent/claude-code.txt"\n            ),\n            env=run_env,'
REPLACEMENT_ARGMAX_3 = '                f"/logs/agent/claude-code.txt; rm -f {_instr_file}"\n            ),\n            env=run_env,'

ALREADY_PATCHED_MARKER_ARGMAX = "_instr_file"


ANCHOR_COLLECT = """\
        if step_cfg is not None:
            hooks.extend(step_cfg.verifier.collect)
        return hooks"""
REPLACEMENT_COLLECT = """\
        if step_cfg is not None:
            hooks.extend(step_cfg.verifier.collect)
        # harbor-patch: builtin collect
        _BUILTIN_CMD = "python3 /harness/scoring/collect_artifacts.py"
        if not any(_BUILTIN_CMD in h.command for h in hooks):
            from harbor.models.task.config import VerifierCollectConfig as _VCC
            hooks.append(_VCC(command=_BUILTIN_CMD))
        return hooks"""
ALREADY_PATCHED_MARKER_COLLECT = "harbor-patch: builtin collect"


ANCHOR_JUDGE_MODEL_1 = """\
        with self.agent_environment.with_default_user(user):
            verifier = VerifierFactory.create_verifier_from_config(
                self.config.verifier,
                task=self.task,
                trial_paths=self.paths,
                environment=self.agent_environment,
                override_env=self.config.verifier.env or None,"""
REPLACEMENT_JUDGE_MODEL_1 = """\
        with self.agent_environment.with_default_user(user):
            _ov_env = dict(self.config.verifier.env or {})
            _ov_env.setdefault("JUDGE_MODEL", "gpt-5.6-sol")
            verifier = VerifierFactory.create_verifier_from_config(
                self.config.verifier,
                task=self.task,
                trial_paths=self.paths,
                environment=self.agent_environment,
                override_env=_ov_env or None,"""

ANCHOR_JUDGE_MODEL_2 = """\
                verifier = VerifierFactory.create_verifier_from_config(
                    self.config.verifier,
                    task=self.task,
                    trial_paths=self.paths,
                    environment=target_env,
                    override_env=self.config.verifier.env or None,"""
REPLACEMENT_JUDGE_MODEL_2 = """\
                _ov_env = dict(self.config.verifier.env or {})
                _ov_env.setdefault("JUDGE_MODEL", "gpt-5.6-sol")
                verifier = VerifierFactory.create_verifier_from_config(
                    self.config.verifier,
                    task=self.task,
                    trial_paths=self.paths,
                    environment=target_env,
                    override_env=_ov_env or None,"""
ALREADY_PATCHED_MARKER_JUDGE_MODEL = '_ov_env.setdefault("JUDGE_MODEL"'


# --- Pre-baked Claude Code CLI ------------------------------------------------
# ClaudeCode.install() reaches the network twice inside the container: apt-get
# for curl/procps, then a bootstrap.sh download from downloads.claude.ai. Both
# run BEFORE the agent phase, and both die once the container's default network
# is `internal: true` (tools/network/egress-proxy/overlay.yaml).
#
# The bundles pre-bake the CLI at build time instead, where the network is still
# open, so these two commands have nothing left to do. They are made no-ops
# rather than deleted: an image WITHOUT a baked CLI still installs normally, so
# a bundle that forgets the Dockerfile line degrades to the old behaviour rather
# than failing to start an agent.
#
# The guard is plain shell on purpose. Probing from Python would mean parsing an
# exec result whose shape is not part of harbor's contract.
_Q = chr(34)

ANCHOR_PREBAKE_ROOT = (
    '                ' + _Q + 'if command -v apk &> /dev/null; then' + _Q + '\n'
    '                ' + _Q + '  apk add --no-cache curl bash nodejs npm procps;' + _Q
)

REPLACEMENT_PREBAKE_ROOT = (
    '                ' + _Q + 'if command -v claude &> /dev/null; then' + _Q + '\n'
    "                '  echo " + _Q + "harbor-patch: claude pre-baked; skipping apt" + _Q + ";'\n"
    '                ' + _Q + ' elif command -v apk &> /dev/null; then' + _Q + '\n'
    '                ' + _Q + '  apk add --no-cache curl bash nodejs npm procps;' + _Q
)

ANCHOR_PREBAKE_AGENT = (
    '                ' + _Q + 'set -euo pipefail; ' + _Q + '\n'
    '                ' + _Q + 'if command -v apk &> /dev/null; then' + _Q
)

REPLACEMENT_PREBAKE_AGENT = (
    '                ' + _Q + 'set -euo pipefail; ' + _Q + '\n'
    '                ' + _Q + 'if command -v claude &> /dev/null; then' + _Q + '\n'
    "                '  echo " + _Q + "harbor-patch: claude pre-baked; skipping bootstrap" + _Q + ";'\n"
    '                ' + _Q + ' elif command -v apk &> /dev/null; then' + _Q
)

ALREADY_PATCHED_MARKER_PREBAKE = "harbor-patch: claude pre-baked"

# Harbor has its own early return at the top of install():
#
#     if await self._installed_claude_satisfies_version(environment):
#         return
#
# Verified present in 0.13.2, 0.20.0 and 0.21.0 -- it is NOT new, so its
# presence alone does not mean the guard below is unnecessary. This patch was
# written anyway, which implies harbor's check does not fire in this harness
# (its probe runs through environment.exec, not exec_as_agent, so a claude that
# is pre-baked for one user can be invisible to the other).
#
# So this constant is used only as a FALLBACK: it is consulted when the anchors
# are gone, to distinguish "harbor restructured and still has some protection"
# from "no protection at all". Where the anchors still match, the patch is
# applied as before. Order matters -- see the prebake block in main().
#
# What changed in 0.21.0: the inline `apk add --no-cache curl bash nodejs npm
# procps` root block that ANCHOR_PREBAKE_ROOT targets was replaced by a call to
# ensure_system_dependencies(), so that anchor can never match again there.
NATIVE_PREBAKE_GUARD = "_installed_claude_satisfies_version"


ANCHOR_FALLBACK = """\
        CliFlag(
            "fallback_model",
            cli="--fallback-model",
            type="str",
        ),"""


# --- Bedrock: ARN model ids and alias pinning ---------------------------------
# CC_MODE=bedrock (scripts/run_task.sh) hands harbor a Bedrock model id or an
# inference-profile ARN as --model. Two things in ClaudeCode.run() get that
# wrong for an ARN:
#
#   1. `if "/" in self.model_name: split("/", 1)[-1]` is meant to strip a
#      Harbor-style "provider/model" prefix, but an ARN carries exactly one "/"
#      (…:application-inference-profile/<id>) and is cut down to "<id>", which
#      Bedrock rejects as an unknown model.
#   2. The sonnet/opus/haiku/subagent aliases are pinned to ANTHROPIC_MODEL
#      only under a custom ANTHROPIC_BASE_URL. A Bedrock API key scoped to one
#      inference profile cannot invoke Bedrock's default haiku id, so any
#      alias call would fail; pin them under Bedrock too, as harbor already
#      does for every other single-model endpoint.
#
# Hard failure on drift, like the thinking flags: the anchors sit in harbor's
# own Bedrock branch, and a Bedrock run on an unpatched harbor dies on its
# first model call with an error that reads like a bad model id.
ANCHOR_BEDROCK_ARN = """\
                if "/" in self.model_name:
                    env["ANTHROPIC_MODEL"] = self.model_name.split("/", 1)[-1]"""
REPLACEMENT_BEDROCK_ARN = """\
                # harbor-patch: bedrock -- an ARN's single "/" is not a provider prefix
                if "/" in self.model_name and not self.model_name.startswith("arn:"):
                    env["ANTHROPIC_MODEL"] = self.model_name.split("/", 1)[-1]"""
ANCHOR_BEDROCK_ALIASES = """\
        if "ANTHROPIC_BASE_URL" in env and "ANTHROPIC_MODEL" in env:
            env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = env["ANTHROPIC_MODEL"]"""
REPLACEMENT_BEDROCK_ALIASES = """\
        if ("ANTHROPIC_BASE_URL" in env or use_bedrock) and "ANTHROPIC_MODEL" in env:
            env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = env["ANTHROPIC_MODEL"]"""
ALREADY_PATCHED_MARKER_BEDROCK = "harbor-patch: bedrock"
# Upstream may fix (1) itself; if its Bedrock branch already knows about ARNs,
# only the alias half is still ours to apply.
NATIVE_BEDROCK_ARN_GUARD = 'startswith("arn:")'


def find_harbor_claude_code() -> Path:
    import shutil
    import subprocess

    try:
        spec = importlib.util.find_spec("harbor.agents.installed.claude_code")
    except (ModuleNotFoundError, ValueError):
        spec = None
    if spec and spec.origin:
        return Path(spec.origin)

    harbor_bin = shutil.which("harbor")
    if not harbor_bin:
        raise RuntimeError(
            "harbor not found in PATH. Install it first: pipx install harbor"
        )

    venv_bin = Path(harbor_bin).resolve().parent
    venv_root = venv_bin.parent
    candidates = sorted(venv_root.glob("lib/python*/site-packages/harbor/agents/installed/claude_code.py"))
    if candidates:
        return candidates[0]

    # Last resort: ask harbor's own interpreter where the module lives. Both
    # candidates can be absent -- a `harbor` shim on PATH that is not inside a
    # venv at all, which is exactly what a test stub looks like. Calling
    # subprocess.run on a path that does not exist raises FileNotFoundError from
    # deep inside subprocess, burying the RuntimeError below that actually says
    # what to do about it. Check first, and let that message be the one the
    # operator sees.
    venv_python = venv_bin / "python3"
    if not venv_python.exists():
        venv_python = venv_bin / "python"
    if venv_python.exists():
        result = subprocess.run(
            [str(venv_python), "-c",
             "import harbor.agents.installed.claude_code as m; print(m.__file__)"],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())

    raise RuntimeError(
        f"Could not locate harbor/agents/installed/claude_code.py in pipx venv at {venv_root}"
    )


def find_harbor_trial() -> Path:
    claude_code = find_harbor_claude_code()
    harbor_pkg_dir = claude_code.parent.parent.parent
    trial = harbor_pkg_dir / "trial" / "trial.py"
    if trial.exists():
        return trial
    raise RuntimeError(f"Could not locate harbor/trial/trial.py (tried {trial})")


def main() -> None:
    # --audit reports every patch's status without writing anything, and always
    # exits 0. Use it after a harbor upgrade: a normal run stops at the first
    # unapplicable patch, so drift is discovered one patch at a time.
    audit = "--audit" in sys.argv or "--check" in sys.argv

    # Anchors that could not be applied. Collected rather than exited on, so one
    # invocation reports all of them. Same reasoning as the ARG_MAX warning
    # below, extended to the rest: run_task.sh calls this unconditionally under
    # `set -e`, so an early sys.exit(1) blocks every stage of every run AND
    # hides whatever else drifted.
    failures: list[str] = []

    target = find_harbor_claude_code()
    text = target.read_text(encoding="utf-8")
    changed = False

    if ALREADY_PATCHED_MARKER in text:
        print(f"[patch_harbor] Thinking flags: already patched")
    elif ANCHOR not in text:
        print(
            f"[patch_harbor] Thinking flags: NOT applied -- anchor not found in {target}",
            file=sys.stderr,
        )
        failures.append(f"thinking flags  ({target.name})")
    else:
        text = text.replace(ANCHOR, ANCHOR + PATCH, 1)
        changed = True
        print(f"[patch_harbor] Thinking flags: patched")

    if ALREADY_PATCHED_MARKER_ARGMAX in text:
        print(f"[patch_harbor] ARG_MAX fix: already applied")
    elif ANCHOR_ARGMAX_1 not in text:
        # A drifted anchor is not a reason to take the whole harness down.
        #
        # This used to sys.exit(1), which meant a patch that no longer applies
        # blocked every stage of every run -- run_task.sh calls this script
        # unconditionally at dispatch, under `set -e`. Harbor 0.13.2 passes the
        # instruction inline as shlex.quote(instruction) (claude_code.py:1258,
        # :1414), while these anchors target an instruction_env_var form from a
        # different harbor release, so on this install the patch cannot apply at
        # all and the harness could not run anything.
        #
        # What is lost by continuing: the instruction goes on the command line,
        # so a bundle whose instruction.md approaches ARG_MAX (1 MiB on Linux)
        # would fail with "Argument list too long". Bundles here are ~1.5 KB, so
        # the warning is the proportionate response -- but it is printed loudly
        # rather than swallowed, because the day a bundle does get large this is
        # the only notice anyone gets.
        print(
            f"[patch_harbor] WARNING: ARG_MAX fix NOT applied -- anchor not found in {target}\n"
            "  This harbor passes the instruction on the command line. Fine for the\n"
            "  bundles in this repo (~1.5 KB); a bundle approaching ARG_MAX (1 MiB)\n"
            "  would fail with 'Argument list too long'. Re-anchor this patch if that\n"
            "  ever happens.",
            file=sys.stderr,
        )
    else:
        text = text.replace(ANCHOR_ARGMAX_1, REPLACEMENT_ARGMAX_1, 1)
        text = text.replace(ANCHOR_ARGMAX_2, REPLACEMENT_ARGMAX_2, 1)
        text = text.replace(ANCHOR_ARGMAX_3, REPLACEMENT_ARGMAX_3, 1)
        changed = True
        print(f"[patch_harbor] ARG_MAX fix: applied")

    if '"fallback_model"' not in text:
        print(f"[patch_harbor] Fallback model removal: already done")
    elif ANCHOR_FALLBACK not in text:
        print(
            f"[patch_harbor] Fallback model removal: NOT applied -- anchor not found in {target}",
            file=sys.stderr,
        )
        failures.append(f"fallback_model removal  ({target.name})")
    else:
        text = text.replace(ANCHOR_FALLBACK, "", 1)
        changed = True
        print(f"[patch_harbor] Fallback model removal: applied")

    if ALREADY_PATCHED_MARKER_PREBAKE in text:
        print(f"[patch_harbor] Pre-baked CLI guard: already applied")
    elif ANCHOR_PREBAKE_ROOT in text and ANCHOR_PREBAKE_AGENT in text:
        text = text.replace(ANCHOR_PREBAKE_ROOT, REPLACEMENT_PREBAKE_ROOT, 1)
        text = text.replace(ANCHOR_PREBAKE_AGENT, REPLACEMENT_PREBAKE_AGENT, 1)
        changed = True
        print(f"[patch_harbor] Pre-baked CLI guard: applied")
    elif NATIVE_PREBAKE_GUARD in text:
        # Anchors gone (harbor >= 0.21.0 restructured install()), but harbor's
        # own _installed_claude_satisfies_version early return is still there.
        # Non-fatal: blocking every run over a patch that has no place left to
        # apply is worse than proceeding on harbor's own protection. Loud
        # because that protection is not identical -- harbor probes via
        # environment.exec, so if a run now fails during agent setup trying to
        # reach the network, this line is the first place to look.
        print(
            f"[patch_harbor] Pre-baked CLI guard: NOT applied -- anchors gone from {target.name};\n"
            "  relying on harbor's own _installed_claude_satisfies_version early return.\n"
            "  If agent setup starts failing on network access, re-anchor this patch.",
            file=sys.stderr,
        )
    else:
        print(
            f"[patch_harbor] Pre-baked CLI guard: NOT applied -- anchor not found in {target}",
            file=sys.stderr,
        )
        failures.append(f"pre-baked CLI guard  ({target.name})")

    if ALREADY_PATCHED_MARKER_BEDROCK in text:
        print(f"[patch_harbor] Bedrock ARN + aliases: already applied")
    else:
        arn_ok = NATIVE_BEDROCK_ARN_GUARD in text or ANCHOR_BEDROCK_ARN in text
        if not arn_ok or ANCHOR_BEDROCK_ALIASES not in text:
            print(
                f"[patch_harbor] Bedrock ARN + aliases: NOT applied -- anchor not found in {target}",
                file=sys.stderr,
            )
            failures.append(f"bedrock ARN + aliases  ({target.name})")
        else:
            if ANCHOR_BEDROCK_ARN in text:
                text = text.replace(ANCHOR_BEDROCK_ARN, REPLACEMENT_BEDROCK_ARN, 1)
            text = text.replace(ANCHOR_BEDROCK_ALIASES, REPLACEMENT_BEDROCK_ALIASES, 1)
            if ALREADY_PATCHED_MARKER_BEDROCK not in text:
                # The ARN half was native; leave the marker on the alias half so
                # the next run reads "already applied" rather than re-patching.
                text = text.replace(
                    REPLACEMENT_BEDROCK_ALIASES,
                    "        # harbor-patch: bedrock -- aliases pinned under Bedrock too\n"
                    + REPLACEMENT_BEDROCK_ALIASES, 1)
            changed = True
            print(f"[patch_harbor] Bedrock ARN + aliases: applied")

    if changed and not audit:
        target.write_text(text, encoding="utf-8")
        print(f"[patch_harbor] Written: {target}")
    elif changed:
        print(f"[patch_harbor] Would write (audit): {target}")
    else:
        print(f"[patch_harbor] Nothing to do: {target}")

    # A missing trial.py is itself drift worth reporting, not a traceback.
    try:
        trial = find_harbor_trial()
    except RuntimeError as exc:
        print(f"[patch_harbor] trial.py: NOT found -- {exc}", file=sys.stderr)
        failures.append("trial.py not found (collect hook + JUDGE_MODEL inject unapplied)")
        _report(failures, audit)
        return
    trial_text = trial.read_text(encoding="utf-8")
    trial_changed = False

    if ALREADY_PATCHED_MARKER_COLLECT in trial_text:
        print(f"[patch_harbor] Collect hook: already applied")
    elif ANCHOR_COLLECT not in trial_text:
        print(
            f"[patch_harbor] Collect hook: NOT applied -- anchor not found in {trial}",
            file=sys.stderr,
        )
        failures.append(f"collect hook  ({trial.name})")
    else:
        trial_text = trial_text.replace(ANCHOR_COLLECT, REPLACEMENT_COLLECT, 1)
        trial_changed = True
        print(f"[patch_harbor] Collect hook: applied")

    if ALREADY_PATCHED_MARKER_JUDGE_MODEL in trial_text:
        print(f"[patch_harbor] JUDGE_MODEL inject: already applied")
    elif ANCHOR_JUDGE_MODEL_1 not in trial_text:
        print(
            f"[patch_harbor] JUDGE_MODEL inject: NOT applied -- anchor not found in {trial}",
            file=sys.stderr,
        )
        failures.append(f"JUDGE_MODEL inject  ({trial.name})")
    else:
        trial_text = trial_text.replace(ANCHOR_JUDGE_MODEL_1, REPLACEMENT_JUDGE_MODEL_1, 1)
        trial_text = trial_text.replace(ANCHOR_JUDGE_MODEL_2, REPLACEMENT_JUDGE_MODEL_2, 1)
        trial_changed = True
        print(f"[patch_harbor] JUDGE_MODEL inject: applied")

    if trial_changed and not audit:
        trial.write_text(trial_text, encoding="utf-8")
        print(f"[patch_harbor] Written: {trial}")
    elif trial_changed:
        print(f"[patch_harbor] Would write (audit): {trial}")

    _report(failures, audit)


def _report(failures: list[str], audit: bool) -> None:
    """Print one consolidated verdict and set the exit code.

    Every patch is attempted before this runs, so a harbor upgrade yields the
    full list of drifted anchors in one go instead of one per invocation.
    """
    if not failures:
        print("[patch_harbor] All patches accounted for.")
        return

    print(f"\n[patch_harbor] ---- {len(failures)} patch(es) could not be applied ----",
          file=sys.stderr)
    for name in failures:
        print(f"  MISS  {name}", file=sys.stderr)
    print(
        "\n  Harbor's source has drifted from these anchors -- most likely it was\n"
        "  upgraded. For each one, either re-anchor it against the new source, or\n"
        "  confirm harbor now provides the behaviour natively and detect that\n"
        "  instead (see NATIVE_PREBAKE_GUARD for the worked example).\n"
        "  Re-run with --audit to re-check without writing.",
        file=sys.stderr,
    )
    if not audit:
        sys.exit(1)


if __name__ == "__main__":
    main()
