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
# is `internal: true` (services/egress-proxy/overlay.yaml).
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


ANCHOR_FALLBACK = """\
        CliFlag(
            "fallback_model",
            cli="--fallback-model",
            type="str",
        ),"""


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
    target = find_harbor_claude_code()
    text = target.read_text(encoding="utf-8")
    changed = False

    if ALREADY_PATCHED_MARKER in text:
        print(f"[patch_harbor] Thinking flags: already patched")
    elif ANCHOR not in text:
        print(
            f"[patch_harbor] ERROR: Anchor for thinking flags not found in {target}\n"
            "Harbor may have been updated and this patch needs revision.",
            file=sys.stderr,
        )
        sys.exit(1)
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
            f"[patch_harbor] ERROR: Anchor for fallback_model removal not found in {target}\n"
            "Harbor may have been updated and this patch needs revision.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        text = text.replace(ANCHOR_FALLBACK, "", 1)
        changed = True
        print(f"[patch_harbor] Fallback model removal: applied")

    if ALREADY_PATCHED_MARKER_PREBAKE in text:
        print(f"[patch_harbor] Pre-baked CLI guard: already applied")
    elif ANCHOR_PREBAKE_ROOT not in text or ANCHOR_PREBAKE_AGENT not in text:
        print(
            f"[patch_harbor] ERROR: Anchor for pre-baked CLI guard not found in {target}\n"
            "Harbor may have updated and this patch needs revision.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        text = text.replace(ANCHOR_PREBAKE_ROOT, REPLACEMENT_PREBAKE_ROOT, 1)
        text = text.replace(ANCHOR_PREBAKE_AGENT, REPLACEMENT_PREBAKE_AGENT, 1)
        changed = True
        print(f"[patch_harbor] Pre-baked CLI guard: applied")

    if changed:
        target.write_text(text, encoding="utf-8")
        print(f"[patch_harbor] Written: {target}")
    else:
        print(f"[patch_harbor] Nothing to do: {target}")

    trial = find_harbor_trial()
    trial_text = trial.read_text(encoding="utf-8")
    trial_changed = False

    if ALREADY_PATCHED_MARKER_COLLECT in trial_text:
        print(f"[patch_harbor] Collect hook: already applied")
    elif ANCHOR_COLLECT not in trial_text:
        print(
            f"[patch_harbor] ERROR: Anchor for collect hook not found in {trial}\n"
            "Harbor may have been updated and this patch needs revision.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        trial_text = trial_text.replace(ANCHOR_COLLECT, REPLACEMENT_COLLECT, 1)
        trial_changed = True
        print(f"[patch_harbor] Collect hook: applied")

    if ALREADY_PATCHED_MARKER_JUDGE_MODEL in trial_text:
        print(f"[patch_harbor] JUDGE_MODEL inject: already applied")
    elif ANCHOR_JUDGE_MODEL_1 not in trial_text:
        print(
            f"[patch_harbor] ERROR: Anchor for JUDGE_MODEL inject not found in {trial}\n"
            "Harbor may have been updated and this patch needs revision.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        trial_text = trial_text.replace(ANCHOR_JUDGE_MODEL_1, REPLACEMENT_JUDGE_MODEL_1, 1)
        trial_text = trial_text.replace(ANCHOR_JUDGE_MODEL_2, REPLACEMENT_JUDGE_MODEL_2, 1)
        trial_changed = True
        print(f"[patch_harbor] JUDGE_MODEL inject: applied")

    if trial_changed:
        trial.write_text(trial_text, encoding="utf-8")
        print(f"[patch_harbor] Written: {trial}")


if __name__ == "__main__":
    main()
