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

    if ALREADY_PATCHED_MARKER in text:
        print(f"[patch_harbor] Already patched: {target}")
        return

    if ANCHOR not in text:
        print(
            f"[patch_harbor] ERROR: Anchor not found in {target}\n"
            "Harbor may have been updated and this patch needs revision.",
            file=sys.stderr,
        )
        sys.exit(1)

    patched = text.replace(ANCHOR, ANCHOR + PATCH, 1)
    target.write_text(patched, encoding="utf-8")
    print(f"[patch_harbor] Patched successfully: {target}")


if __name__ == "__main__":
    main()
