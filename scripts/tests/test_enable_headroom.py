"""enable_headroom.sh must not break the Dockerfile it edits.

The pin goes on a `RUN pip install` line. Bundles write that instruction two
ways, and only one of them survived the original implementation:

    RUN pip install --no-cache-dir pytest python-docx        <- one line, fine
    RUN pip install --no-cache-dir \\                          <- continued
        matplotlib \\
        openpyxl

Appending to the line that MATCHES puts the pin after the trailing backslash in
the second form, which ends the continuation. Docker then reads the next line as
an instruction and the build dies with `unknown instruction: matplotlib` -- at
environment-build time, minutes in, having said nothing about headroom.

This has happened to two bundles now. Both times it was fixed by editing the
bundle, which left the cause in place; these pin the behaviour of the tool.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "enable_headroom.sh"
PIN = '"headroom-ai>=0.37,<0.38"'

ONE_LINE = 'RUN pip install --no-cache-dir pytest python-docx\n'
CONTINUED = (
    'RUN pip install --no-cache-dir \\\n'
    '    matplotlib \\\n'
    '    pandas \\\n'
    '    openpyxl\n'
)

COMPOSE = """services:
  main:
    build:
      context: .
    environment:
      WORKSPACE_ROOT: "/workspace"
"""


def _bundle(tmp_path: Path, pip_block: str) -> Path:
    env = tmp_path / "task" / "environment"
    env.mkdir(parents=True)
    (env / "Dockerfile").write_text(
        "FROM python:3.12-slim\n\n"
        "RUN apt-get update && apt-get install -y --no-install-recommends curl \\\n"
        "    && rm -rf /var/lib/apt/lists/*\n\n"
        + pip_block
        + "\nWORKDIR /task\n"
    )
    (env / "docker-compose.yaml").write_text(COMPOSE)
    (tmp_path / "task" / "task.toml").write_text('name = "acme/alpha"\n')
    return tmp_path / "task"


def _run(task: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), str(task), *args],
        capture_output=True, text=True, cwd=str(REPO), timeout=120,
    )


def _instructions(dockerfile: Path) -> list[str]:
    """First token of every line docker would read as an instruction.

    Continuation lines are consumed by the instruction above them; anything that
    surfaces here that is not a real instruction is the bug.
    """
    out, cont = [], False
    for raw in dockerfile.read_text().splitlines():
        line = raw.strip()
        was_cont, cont = cont, line.endswith("\\")
        if not line or line.startswith("#") or was_cont:
            continue
        out.append(line.split()[0])
    return out


VALID = {"FROM", "RUN", "WORKDIR", "COPY", "ENV", "CMD", "ENTRYPOINT", "ARG", "EXPOSE"}


@pytest.mark.skipif(not SCRIPT.is_file(), reason="enable_headroom.sh absent")
@pytest.mark.parametrize("pip_block", [ONE_LINE, CONTINUED], ids=["one-line", "continued"])
def test_the_dockerfile_still_parses_after_the_pin_is_added(tmp_path, pip_block):
    task = _bundle(tmp_path, pip_block)
    proc = _run(task)
    assert proc.returncode == 0, proc.stderr
    df = task / "environment" / "Dockerfile"
    assert PIN in df.read_text(), "pin was not added"
    bad = [i for i in _instructions(df) if i not in VALID]
    assert not bad, (
        f"{bad} would be read as Dockerfile instructions -- the pin broke a line "
        f"continuation:\n{df.read_text()}"
    )


@pytest.mark.skipif(not SCRIPT.is_file(), reason="enable_headroom.sh absent")
@pytest.mark.parametrize("pip_block", [ONE_LINE, CONTINUED], ids=["one-line", "continued"])
def test_the_pin_lands_inside_the_pip_instruction(tmp_path, pip_block):
    """Not merely "the file still parses" -- it has to actually be installed."""
    task = _bundle(tmp_path, pip_block)
    _run(task)
    body = (task / "environment" / "Dockerfile").read_text()
    run_line = [
        blk for blk in body.replace("\\\n", " ").splitlines()
        if blk.startswith("RUN pip install")
    ]
    assert run_line, body
    assert PIN in run_line[0], f"pin is outside the pip instruction:\n{body}"


@pytest.mark.skipif(not SCRIPT.is_file(), reason="enable_headroom.sh absent")
@pytest.mark.parametrize("pip_block", [ONE_LINE, CONTINUED], ids=["one-line", "continued"])
def test_disable_reverts_byte_identically(tmp_path, pip_block):
    """The script's own docs promise this, and it is what makes re-running free."""
    task = _bundle(tmp_path, pip_block)
    df = task / "environment" / "Dockerfile"
    before = df.read_text()
    _run(task)
    _run(task, "--disable")
    assert df.read_text() == before


@pytest.mark.skipif(not SCRIPT.is_file(), reason="enable_headroom.sh absent")
def test_disable_cleans_up_a_file_the_old_version_corrupted(tmp_path):
    """Files already pinned mid-continuation exist in the tree.

    --disable has to find the pin wherever the previous implementation put it,
    not only where this one does, or those bundles stay broken forever.
    """
    task = _bundle(tmp_path, CONTINUED)
    df = task / "environment" / "Dockerfile"
    df.write_text(df.read_text().replace(
        "RUN pip install --no-cache-dir \\",
        f"RUN pip install --no-cache-dir \\ {PIN}", 1))
    _run(task, "--disable")
    assert PIN not in df.read_text(), df.read_text()
