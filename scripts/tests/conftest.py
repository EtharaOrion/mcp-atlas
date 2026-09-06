"""Shared fixtures for the run_task.sh stage tests.

The one thing in here exists because run_task.sh's harbor stage runs
scripts/patch_harbor.py before it dispatches, and that script locates the harbor
package RELATIVE TO whichever `harbor` is first on PATH -- it globs
<venv>/lib/python*/site-packages/harbor/... where <venv> is the binary's
grandparent.

Any test that shadows `harbor` with a stub therefore points patch_harbor.py at a
tmp dir containing no harbor install, and it raises before harbor is ever
invoked. The symptom is an empty argv file and an assertion about a flag that
was never passed, which reads like a dispatch bug in run_task.sh rather than a
missing fixture.

test_network_policy.py grew its own private copy of this for the same reason.
This is that helper, shared, so the next file to stub `harbor` gets it for free.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


def mirror_harbor_package(tmp_path: Path) -> bool:
    """Mirror the two files patch_harbor.py rewrites into a stub venv layout.

    COPIES, never links: the patcher rewrites them in place, and a link would
    edit the real harbor install out from under every other test on the machine.

    Returns False when harbor is not installed at all, so callers can skip
    rather than fail -- a laptop without harbor is not a broken run_task.sh.
    """
    real_harbor = shutil.which("harbor")
    if not real_harbor:
        return False

    venv_root = Path(real_harbor).resolve().parent.parent
    for cc in venv_root.glob(
        "lib/python*/site-packages/harbor/agents/installed/claude_code.py"
    ):
        rel = cc.relative_to(venv_root)
        pkg = cc.parent.parent.parent
        for src, dest_rel in (
            (pkg / "agents" / "installed" / "claude_code.py", rel),
            (pkg / "trial" / "trial.py",
             rel.parent.parent.parent / "trial" / "trial.py"),
        ):
            if src.exists():
                dest = tmp_path / dest_rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(src.read_text())
        return True
    return False


@pytest.fixture
def harbor_package_mirror(tmp_path):
    """Make `tmp_path` look enough like a harbor venv for patch_harbor.py."""
    if not mirror_harbor_package(tmp_path):
        pytest.skip("harbor is not installed; cannot mirror its package")
    return tmp_path
