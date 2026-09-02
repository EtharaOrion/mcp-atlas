"""Mask host-local filesystem paths in text destined for a delivery bundle.

Harbor writes absolute host paths into its job/trial bookkeeping (result.json's
`trial_uri`, config.json's `trials_dir`/`jobs_dir`, lock.json's invocation).
Those files are copied into run folders and delivery bundles, which is how
strings like `/Users/<name>/...` and `file:///Users/...` end up in shipped
artifacts.

The rewrite has two tiers:

* a path that contains a recognizable repo anchor (`output/`, `tasks/`,
  `jobs/`, `delivery_output/`) is cut down to the anchor-relative form, so
  `file:///Users/x/dev/harness/output/t/r` becomes `output/t/r` — still a
  usable pointer inside the bundle;
* any other home-rooted path has its `/Users/<name>` or `/home/<name>` head
  replaced with `~`, which keeps the tail readable without naming the machine.

Only `/Users/...` and `/home/...` roots are touched: container paths such as
`/workspace`, `/logs` or `/tmp` are part of the recorded run and must survive
verbatim.
"""
from __future__ import annotations

import re
from pathlib import Path

# A host-local path: optional file:// scheme, a /Users/<name> or /home/<name>
# head, then everything up to whitespace or a JSON string delimiter.
_LOCAL_PATH_RE = re.compile(
    r"(?:file://)?/(?:Users|home)/[^/\s\"'\\]+(?P<rest>(?:/[^\s\"'\\]*)?)"
)

# A repo anchor, either mid-path or at the end of the path. "delivery_output"
# is listed before "output" so the longer name wins at the same position.
_ANCHOR_RE = re.compile(r"/(?:delivery_output|output|tasks|jobs)(?=/|$)")


def mask_local_paths(text: str) -> str:
    """Return `text` with every host-local path masked (see module docstring)."""

    def _repl(m: re.Match) -> str:
        rest = m.group("rest") or ""
        a = _ANCHOR_RE.search(rest)
        if a:
            return rest[a.start() + 1 :]
        return "~" + rest

    return _LOCAL_PATH_RE.sub(_repl, text)


def mask_file(path: Path) -> bool:
    """Mask one text file in place. Returns True if the file was changed."""
    original = path.read_text(encoding="utf-8", errors="replace")
    masked = mask_local_paths(original)
    if masked != original:
        path.write_text(masked, encoding="utf-8")
        return True
    return False


# Extensions it is safe to treat as text when sweeping a whole bundle.
_TEXT_SUFFIXES = {".json", ".jsonl", ".txt", ".md", ".xml", ".yaml", ".yml", ".log",
                  ".toml", ".py", ".csv", ".html", ".cfg", ".ini"}


def mask_tree(root: Path) -> list[Path]:
    """Mask every text file under `root` in place; return the changed files."""
    changed: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in _TEXT_SUFFIXES:
            if mask_file(p):
                changed.append(p)
    return changed
