"""The single seam through which every Light* app reads its corpus.

Two invariants carry the whole design. Both are structural: they are enforced
by what this module *is*, not by what contributors remember to do.

I1 -- THE CACHE HOLDS ONLY STRINGS, never a parsed object.
    ``load()`` is ``yaml.safe_load(cached_text)``, so every call allocates a
    fresh object graph. There is nothing shared to leak between sessions, so
    there is no ``deepcopy`` to forget and no shallow-copy trap. This is
    strictly stronger than "deep-copy on read": a deepcopy rule is one a
    future contributor can violate, whereas there is simply no object in the
    cache to hand out. Testable in one line -- every value is a ``str``.

Extra world data reaches a task through the bundle's own ``world_data/``
directory, mounted read-only and applied by ``software/utils/world_data.py``.
This module only ever reads the app's shipped corpus.

This module has no write path. Not "we don't call it" -- the function is not
written. The only serialisation here is ``yaml.safe_dump`` to a *string* for
the cache; nothing in this file opens a file for writing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# str(resolved corpus path) -> YAML text. Only ever str -- see I1.
_CACHE: Dict[str, str] = {}

# Apps whose corpus files have already been read into the cache.
_BUILT: set = set()


def app_name_for_path(corpus_path) -> Optional[str]:
    """``software/<App>/corpus/<file>.yaml`` -> ``"<App>"``, else None."""
    p = Path(corpus_path).resolve()
    return p.parent.parent.name if p.parent.name == "corpus" else None


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def _corpus_files(app_dir: Path) -> List[Path]:
    cdir = Path(app_dir) / "corpus"
    if not cdir.is_dir():
        return []
    return sorted([p for p in cdir.iterdir()
                   if p.suffix in (".yaml", ".yml") and p.is_file()])


def build_app(app_name: str, app_dir) -> None:
    """Parse every corpus file for one app and cache the result AS TEXT (I1).

    Idempotent: building an app twice in one process is a no-op.
    """
    if app_name in _BUILT:
        return
    app_dir = Path(app_dir)
    for f in _corpus_files(app_dir):
        _CACHE.setdefault(str(f.resolve()), f.read_text())
    _BUILT.add(app_name)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def load(corpus_path) -> Any:
    """Return a FRESH parse of a corpus file. The per-login read path.

    Returns exactly what ``yaml.safe_load`` would have returned for the file --
    a dict, a bare list, or None for an empty file -- so callers keep their own
    ``or {}`` handling and this stays a pure substitution.
    """
    p = Path(corpus_path).resolve()
    key = str(p)
    if key not in _CACHE:
        app = app_name_for_path(p)
        if app:
            build_app(app, p.parent.parent)
        # build_app is not a guarantee that THIS file landed in the cache: it is
        # a no-op once the app is in _BUILT, and _corpus_files only picks up
        # .yaml/.yml, so a later file or a non-YAML sibling inside corpus/ falls
        # straight through it. Reading through here is what keeps the line below
        # from raising a bare KeyError on a path that exists. A path that does
        # NOT exist now raises FileNotFoundError, which names the real problem.
        # Still cached as text, so I1 holds for every entry without exception.
        if key not in _CACHE:
            _CACHE[key] = p.read_text()
    return yaml.safe_load(_CACHE[key])


def reset() -> None:
    """Drop every cached corpus.

    TEARDOWN HELPER ONLY -- nothing in the serving path calls this, and nothing
    should: the cache is process-local, so a shutdown hook would only be racing
    the interpreter to free memory that is about to be freed anyway. It exists
    for tests, which need a clean cache between cases. The previous docstring
    claimed it ran "on lifespan shutdown"; it never has.
    """
    _CACHE.clear()
    _BUILT.clear()


