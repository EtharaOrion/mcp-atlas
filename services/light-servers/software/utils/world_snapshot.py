"""Seedless world snapshots.

Freeze a session's *generated* world so it can be loaded verbatim at login
instead of being rolled from a seed (ETOM-style: the world is read, not rolled).

Why pickle rather than hand-written JSON per app: a session's world is an
arbitrary object graph — typed dataclasses, nested lists/dicts, a `random.Random`
that is *shared* by reference with helpers like `TimeMachine`. Pickle preserves
that graph, including the shared-rng identity and the exact post-generation rng
state, so runtime id/timestamp/network minting reproduces the old seeded sequence
byte-for-byte. One utility works for all ~140 apps; no per-app serializer.

Recipe per app:
  1. BEFORE making the session seedless, run a bake against the still-seed-based
     code:  bake_session(core_session_at_seed_42, path)
     (bake while the core class is imported under its normal module name, so the
     pickle's class reference matches the one that exists at load time).
  2. Make the core session's __init__ seedless:
        restore_into(self, path); self.os = <live connector>
     (restore_into copies the frozen attributes onto `self`; pickle never calls
     __init__, so a changed/seedless class body is fine.)

A4 reconciliation -- seed vs. content, two different guarantees:
  `resolve_seed()` below always drives `self.rng`, so ids/timestamps/minted
  values are reproducible for a given seed (tests/test_seed_plumbing.py).
  That is NOT the same as "content varies by seed" -- ~102 of 138 apps load
  their substantive content (listings, tickets, messages, ...) from a static
  per-app corpus that a seed change never touches; only ~36 apps' content
  actually differs across seeds. See software/utils/seed_content_registry.py
  for the empirically-derived per-app answer. Each app's authored world now
  lives in-code -- baked into software/<App>/corpus/*.yaml where the corpus can
  hold it, else in software/<App>/world.json (both loaded via world_data at
  boot). For task authors who need *different* content for a seed-static app,
  the mechanism is a software.utils.world_data override dir or
  software.utils.fixtures, not seed. run_benchmark.py logs a one-time advisory
  when a task's declared seed can't actually do anything for one of its apps.
"""
from __future__ import annotations

import functools
import hashlib
import inspect
import json
import logging
import os
import pickle
import sys
from pathlib import Path

_log = logging.getLogger("complexmcp.world_snapshot")

# Per-connection attributes that must NOT be frozen into the world — they are
# rebuilt from the live login (os_cfg) each session.
_LIVE_ATTRS = ("os",)


def _caller_app_label() -> str:
    """Best-effort app name for a boot-mode log line: the directory name of
    whichever module called seed_mode() (software/<App>/foo.py -> "<App>").
    Best-effort only — falls back to "?" if the stack is shallower than
    expected (e.g. seed_mode() called directly from a REPL/test)."""
    try:
        caller = inspect.stack()[2]  # [0]=this fn, [1]=seed_mode, [2]=app __init__
        return Path(caller.filename).resolve().parent.name
    except Exception:
        return "?"


# ---------------------------------------------------------------------------
# Seed architecture (default). The harness is seed-based: __init__ ROLLS the
# world from a seed (random.Random(seed)) so different seeds give different
# worlds (anti-memorisation, seed-based re-tiering). seed=42 reproduces the
# original frozen fixture exactly.
#
# The seedless static snapshot (world.pkl) is now an explicit escape hatch only:
# set COMPLEXMCP_SEED_MODE=static (or seedless/off/0/false/no) to load it.
#
# Log
# ---------------------------------------------------------------------------
def seed_mode() -> bool:
    """True iff apps should generate their world from a seed. This is the DEFAULT;
    only an explicit opt-out loads the frozen static snapshot."""
    raw = os.environ.get("COMPLEXMCP_SEED_MODE", "seed")
    seeded = raw.strip().lower() not in (
        "static", "seedless", "snapshot", "frozen", "0", "false", "off", "no",
    )
    app = _caller_app_label()
    if seeded:
        _log.info("[seed-mode] %s booting seed=%s (COMPLEXMCP_SEED_MODE=%r)",
                   app, resolve_seed(), raw)
    else:
        _log.warning(
            "[seed-mode] %s booting SEEDLESS from frozen world.pkl "
            "(COMPLEXMCP_SEED_MODE=%r) — gt_env is baked per-task-seed, so this "
            "world will NOT match gt_env unless world.pkl was baked at this "
            "task's seed. If this is unexpected, unset COMPLEXMCP_SEED_MODE.",
            app, raw)
    return seeded


def resolve_seed(seed=None) -> int:
    """The seed to roll the world from: explicit arg wins, else $COMPLEXMCP_SEED,
    else 42 (the fixture's own seed)."""
    if seed is not None:
        return int(seed)
    env = os.environ.get("COMPLEXMCP_SEED")
    if env not in (None, ""):
        return int(env)
    return 42


_DIGESTS_PATH = Path(__file__).resolve().parent / "world_snapshot_digests.json"
_SOFTWARE_ROOT = Path(__file__).resolve().parent.parent


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_key(path) -> str:
    """Manifest key for `path`: its location relative to software/."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(_SOFTWARE_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _load_digests() -> dict:
    if not _DIGESTS_PATH.is_file():
        return {}
    try:
        with open(_DIGESTS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"world snapshot digest manifest unreadable at {_DIGESTS_PATH}: {exc}"
        ) from exc


# What a world snapshot is allowed to construct.
#
# Two layers guard this file and they fail independently. _verify_snapshot
# checks that a snapshot's bytes are the recorded ones, and the manifest it
# checks against is rewritten by _record_snapshot on every bake, so a writer
# who can replace a .pkl can also replace its digest in the same commit. That
# layer therefore assumes the writer is honest. This one does not: it bounds
# what a snapshot can construct even when its digest checks out, which is what
# actually closes the arbitrary-code-execution channel unpickling opens.
#
# The rule is by module origin rather than by class name. A snapshot holds an
# arbitrary object graph of the app's own dataclasses, so enumerating class
# names would need editing every time an app gains a field type, and would
# fail at load time rather than review time when someone forgot. Origin is
# the property that actually matters: a class defined by this repository's own
# world model is fine, and `os.system` or `subprocess.Popen` is not, whatever
# either is called.
# Builtins are enumerated one by one rather than allowed as a module, because
# `builtins` is where the classic pickle escapes live. Every name here is an
# inert container or scalar type. `eval`, `exec`, `open`, `getattr`,
# `__import__`, and `type` are deliberately absent: the first five are the
# standard gadget set, and `type` would let a payload build new classes.
_BUILTIN_TYPES = frozenset(
    {
        "list", "dict", "set", "frozenset", "tuple", "str", "bytes",
        "bytearray", "int", "float", "bool", "complex", "object",
    }
)

_STDLIB_ALLOWED = frozenset(
    {("builtins", n) for n in _BUILTIN_TYPES}
    | {
        ("random", "Random"),
        ("datetime", "datetime"),
        ("datetime", "date"),
        ("datetime", "time"),
        ("datetime", "timedelta"),
        ("datetime", "timezone"),
        ("collections", "OrderedDict"),
        ("collections", "defaultdict"),
    }
)


@functools.lru_cache(maxsize=1)
def _software_module_names() -> frozenset:
    """Every module name that exists as a file under software/.

    Derived from the filesystem, never from the payload, so a crafted snapshot
    cannot widen it. Apps are imported under their bare stem, for example
    software/LightAuction/auction.py as `auction`, so both the bare stem and
    the dotted path are recorded.
    """
    names = set()
    for path in _SOFTWARE_ROOT.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        names.add(path.stem)
        try:
            rel = path.relative_to(_SOFTWARE_ROOT.parent)
        except ValueError:
            continue
        names.add(rel.with_suffix("").as_posix().replace("/", "."))
    return frozenset(names)


def _defined_under_software(obj) -> bool:
    """Whether `obj` was defined by a file inside software/."""
    origin = sys.modules.get(getattr(obj, "__module__", None))
    file = getattr(origin, "__file__", None)
    if not file:
        return False
    try:
        Path(file).resolve().relative_to(_SOFTWARE_ROOT)
    except ValueError:
        return False
    return True


class _WorldUnpickler(pickle.Unpickler):
    """Unpickler that constructs only this repository's own world classes.

    `pickle` treats a payload as a program: a crafted snapshot can name any
    importable callable and have it invoked during load. Overriding find_class
    is the supported way to bound that, and it is consulted for every class a
    payload names, so there is no way around it short of a CPython bug.

    The module name is checked before anything is imported, because importing
    a module the payload chose would already run its top-level code. Only once
    the name is known to belong to software/ is the import allowed to happen,
    and the result is then confirmed to be a class that software/ really
    defines, which closes the case where a stem under software/ shadows a
    stdlib module of the same name.
    """

    def find_class(self, module, name):
        if (module, name) in _STDLIB_ALLOWED:
            return super().find_class(module, name)
        if module not in _software_module_names():
            raise pickle.UnpicklingError(
                f"world snapshot names {module}.{name}; {module} is not a "
                "world-model module, so it will not be imported"
            )
        obj = super().find_class(module, name)
        if not isinstance(obj, type):
            raise pickle.UnpicklingError(
                f"world snapshot names {module}.{name}, which is not a class; "
                "refusing to construct it"
            )
        if not _defined_under_software(obj):
            raise pickle.UnpicklingError(
                f"world snapshot names {module}.{name}, which resolves outside "
                "software/; refusing to construct it"
            )
        return obj


def _verify_snapshot(path) -> None:
    """Refuse to unpickle a snapshot whose bytes are not the recorded ones.

    Unpickling executes arbitrary code, so an unrecorded or altered snapshot
    is a code-execution channel. Fail closed rather than load it. This is the
    first of two independent layers; see _WorldUnpickler for the second.
    """
    key = _snapshot_key(path)
    expected = _load_digests().get(key)
    if expected is None:
        raise RuntimeError(
            f"world snapshot {key} is absent from {_DIGESTS_PATH.name}; "
            "refusing to unpickle an unrecorded snapshot"
        )
    actual = _sha256(path)
    if actual != expected:
        raise RuntimeError(
            f"world snapshot {key} failed its integrity check; refusing to "
            f"unpickle (expected {expected}, got {actual})"
        )


def _record_snapshot(path) -> None:
    """Record `path`'s digest after a bake so restore_into will accept it."""
    digests = _load_digests()
    digests[_snapshot_key(path)] = _sha256(path)
    with open(_DIGESTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(digests, fh, indent=2, sort_keys=True)
        fh.write("\n")


def bake_session(core, path) -> None:
    """Pickle `core`'s world to `path`, minus its live connection attrs."""
    stash = {k: getattr(core, k) for k in _LIVE_ATTRS if hasattr(core, k)}
    for k in stash:
        setattr(core, k, None)
    try:
        with open(path, "wb") as fh:
            pickle.dump(core, fh, protocol=pickle.HIGHEST_PROTOCOL)
        _record_snapshot(path)
    finally:
        for k, v in stash.items():
            setattr(core, k, v)


def restore_into(target, path):
    """Load a frozen world (from `path`) onto the live instance `target`.

    Copies the frozen attributes onto `target.__dict__`. The caller is
    responsible for (re)attaching live connection attrs (e.g. `target.os`)
    afterwards. Returns `target`.
    """
    _verify_snapshot(path)
    with open(path, "rb") as fh:
        loaded = _WorldUnpickler(fh).load()
    target.__dict__.update(loaded.__dict__)
    return target
