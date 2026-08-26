#!/usr/bin/env python3
"""Emit a shippable delivery closure with history and remotes stripped.

Why this exists. The delivery repository is checked out as a git submodule
for development, so its working tree necessarily carries a .git pointer and
an origin remote. Handing that directory to a client would ship an object
database, every earlier state recoverable from it, and a remote URL that
discloses internal organisation identity. Deleting .git in place is not the
fix: it breaks submodule resolution for every developer and it does not make
any shipped artifact cleaner, because what ships is what this packer emits.

The rules enforced here are the must_exclude block of delivery/closure.yaml.
This packer copies, strips, then RE-SCANS the emitted tree and fails closed
if anything it was supposed to remove survived. A packer that trusts its own
copy step certifies a cleanliness it never checked.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Directory names that carry git history or fetch capability.
_GIT_NAMES = {
    ".git", ".gitmodules", "objects", "packed-refs", "refs", "logs",
    "shallow", "alternates", "worktrees", "modules",
}
# ".git" appears here and is matched by name, which covers both the
# directory form and the submodule pointer-file form.
_STRIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
_STRIP_FILES = {".gitmodules", ".DS_Store"}
_STRIP_SUFFIX = {".pyc", ".pyo"}
_CRED_HINTS = {".git-credentials", ".netrc", "credentials"}


def _ignore(_dir: str, names: list[str]) -> set[str]:
    out = set()
    for n in names:
        if n in _STRIP_DIRS or n in _STRIP_FILES or n in _CRED_HINTS:
            out.add(n)
        elif any(n.endswith(s) for s in _STRIP_SUFFIX):
            out.add(n)
    return out


def scan_violations(root: Path) -> list[str]:
    """Re-scan an emitted closure. Empty result is the only pass condition."""
    bad: list[str] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        name = p.name
        # .git may be a directory OR a pointer file. A submodule checkout uses
        # the pointer form, which resolves to a full object database elsewhere
        # in the tree, so treating only the directory form as history would
        # miss exactly the case this closure is in.
        if name in _STRIP_DIRS or name == ".git":
            kind = "directory" if p.is_dir() else "pointer file"
            bad.append(f"history/build {kind} survived: {rel}")
        elif p.is_file():
            if name in _STRIP_FILES or name in _CRED_HINTS:
                bad.append(f"excluded file survived: {rel}")
            elif any(name.endswith(s) for s in _STRIP_SUFFIX):
                bad.append(f"build residue survived: {rel}")
            elif name == "config" and any(a in _GIT_NAMES for a in rel.parts):
                bad.append(f"git config survived: {rel}")
    # A remote can only be configured through a git config; if no git metadata
    # survived, no remote survived either. Check explicitly rather than assume.
    for cfg in root.rglob("config"):
        try:
            if "[remote " in cfg.read_text(encoding="utf-8", errors="replace"):
                bad.append(f"remote definition survived: {cfg.relative_to(root)}")
        except OSError:
            continue
    return bad


def pack(closure: Path, out: Path) -> int:
    closure = closure.resolve()
    out = out.resolve()
    if not closure.is_dir():
        print(f"closure not found: {closure}", file=sys.stderr)
        return 2
    identity = closure / "closure.yaml"
    if not identity.is_file():
        print(
            f"refusing to pack: {closure}/closure.yaml is absent, so the emitted "
            "archive would carry no closure identity to reconcile against",
            file=sys.stderr,
        )
        return 2
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(closure, out, ignore=_ignore, symlinks=False)

    violations = scan_violations(out)
    if violations:
        shutil.rmtree(out)
        print("refusing to emit; strip did not hold:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1

    files = sum(1 for p in out.rglob("*") if p.is_file())
    print(f"closure emitted: {out}")
    print(f"  files: {files}")
    print("  history: absent   remotes: absent   build residue: absent")
    print("  verified by re-scan of the emitted tree, not by trusting the copy")
    return 0


def _cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--closure", default="delivery", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    return pack(a.closure, a.out)


if __name__ == "__main__":
    raise SystemExit(_cli())
