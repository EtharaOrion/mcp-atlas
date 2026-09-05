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

    venv_python = venv_bin / "python3"
    if not venv_python.exists():
        venv_python = venv_bin / "python"
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
        print(
            f"[patch_harbor] ERROR: Anchor for ARG_MAX fix not found in {target}\n"
            "Harbor may have been updated and this patch needs revision.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        text = text.replace(ANCHOR_ARGMAX_1, REPLACEMENT_ARGMAX_1, 1)
        text = text.replace(ANCHOR_ARGMAX_2, REPLACEMENT_ARGMAX_2, 1)
        text = text.replace(ANCHOR_ARGMAX_3, REPLACEMENT_ARGMAX_3, 1)
        changed = True
        print(f"[patch_harbor] ARG_MAX fix: applied")

    if changed:
        target.write_text(text, encoding="utf-8")
        print(f"[patch_harbor] Written: {target}")
    else:
        print(f"[patch_harbor] Nothing to do: {target}")


if __name__ == "__main__":
    main()
