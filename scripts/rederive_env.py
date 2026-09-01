#!/usr/bin/env python3
"""Re-derive a task's grading baselines against the world the servers will
actually serve.

Why this is a prerequisite and not a follow-up
----------------------------------------------
``tests/old_env.json`` and ``tests/gt_env.json`` are baked from the stock
world. Inject a row and it lands in the post-run dump but is in neither
baseline, so ``_state_diff()`` in ``tests/test_outputs.py`` reports it under
``unexpected`` and the **completion** channel scores 0.0 on an otherwise
perfect run. (The misbehave channel is unaffected: ``_state_misbehaved()``
only compares keys present in *both* the end dump and ``old_env``, so a new
entity is outside its intersection. Completion is the one that breaks.)

How the baselines are built
---------------------------
The same way ``task.toml``'s ``gt_env_status`` says the committed ones were:
in-process, at the task's seed, no Docker.

  old_env = each app's ``get_session_dict()`` on a fresh session
  gt_env  = the same, with ``tests/oracle.json``'s declared writes applied
            through the app's own session methods -- so the ground truth stays
            a product of the server rather than a hand-edited JSON file

The dump is wrapped as ``{"status": "ok", "output": ...}`` to match what
``tests/state_dump.py`` captures from ``logout`` at grading time.

Usage
-----
    scripts/rederive_env.py tasks/<task>                     # dry run, prints the delta
    scripts/rederive_env.py tasks/<task> --write             # rewrite both baselines
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import re
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIGHT_SERVERS = REPO / "services" / "light-servers"


def _session_class(app: str):
    """The app's core session class -- the object ``app.py`` delegates to."""
    app_dir = LIGHT_SERVERS / "software" / app
    for py in sorted(app_dir.glob("*.py")):
        if py.stem in ("app", "__init__"):
            continue
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            mod = importlib.import_module(f"software.{app}.{py.stem}")
        for name in dir(mod):
            obj = getattr(mod, name)
            # The wrapper in session.py is also named *Session but only
            # delegates; the core class is the one that can dump the world.
            # Requiring get_session_dict picks the right one regardless of
            # which module sorts first (LightEtsy: etsy.py < session.py, but
            # LightZendesk: session.py < zendesk.py -- alphabetical order is
            # not a reliable discriminator).
            if (isinstance(obj, type) and name.endswith("Session")
                    and obj.__module__ == mod.__name__
                    and hasattr(obj, "get_session_dict")):
                return obj
    raise SystemExit(f"[rederive] no session class found for {app}")


def _dump(session) -> dict:
    return {"status": "ok", "output": session.get_session_dict()}


def _build(app: str, seed: int):
    cls = _session_class(app)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return cls(None, seed=seed)


def _apply_oracle(session, app: str, calls: list) -> None:
    for c in calls:
        name = c.get("call")
        args = {k: v for k, v in (c.get("args") or {}).items() if k != "session_id"}
        fn = getattr(session, name, None)
        if fn is None:
            raise SystemExit(
                f"[rederive] {app}: oracle declares {name!r} but the session has no "
                f"such method. Apply it by hand or fix tests/oracle.json."
            )
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            fn(**args)


def _counts(env: dict) -> dict:
    return {a: {c: len(r) for c, r in b["output"].items() if isinstance(r, list)}
            for a, b in env.items()}


# Must stay in sync with tests/test_outputs.py::_VOLATILE_FIELDS -- a field the
# grader ignores but this checker does not produces a false "baselines are
# stale" report, and --write would then churn the bundle for nothing.
_VOLATILE = ("updated_timestamp", "updated_at", "last_modified")


def _entities(env: dict) -> dict:
    """Flatten to {(app, collection, key): row}, matching the keying that
    ``tests/test_outputs.py`` grades on -- so a difference reported here is
    exactly a difference the state channel would score."""
    flat = {}
    for app, blob in (env or {}).items():
        # The baselines carry a `_canary` string alongside the per-app blobs;
        # every other value here is a {"status", "output"} mapping. Without this
        # the canary reaches .get() and takes the whole report down.
        if not isinstance(blob, dict):
            continue
        for coll, rows in (blob.get("output") or {}).items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                key = (row.get("listing_id") or row.get("id") or row.get("receipt_id")
                       or json.dumps(row, sort_keys=True, default=str)[:64])
                flat[(app, coll, str(key))] = {k: v for k, v in row.items()
                                               if k not in _VOLATILE}
    return flat


def _report(name: str, derived: dict, committed: dict) -> bool:
    """Print the entity-level delta. Returns True when they agree."""
    d, c = _entities(derived), _entities(committed)
    added = sorted(set(d) - set(c))
    dropped = sorted(set(c) - set(d))
    changed = sorted(k for k in set(d) & set(c) if d[k] != c[k])
    if not (added or dropped or changed):
        print(f"[rederive] {name}: matches committed")
        return True
    print(f"[rederive] {name}: DIFFERS from committed")
    for label, keys in (("only in derived", added), ("only in committed", dropped),
                        ("changed", changed)):
        for k in keys[:10]:
            extra = ""
            if label == "changed":
                fields = sorted(f for f in set(d[k]) | set(c[k]) if d[k].get(f) != c[k].get(f))
                extra = f"  fields={fields[:6]}"
            print(f"[rederive]    {label}: {k[0]}.{k[1]}.{k[2]}{extra}")
        if len(keys) > 10:
            print(f"[rederive]    ... and {len(keys) - 10} more {label}")
    return False


def _world_data_dir(task_dir: Path):
    """The host path the task's compose maps to ``COMPLEXMCP_WORLD_DATA``.

    Bundles build their world with the world_data overlay
    (``hydrate()`` / ``load_state()``). Dropping
    that env var re-derives the STOCK world, which differs from the served
    world in every entity the overlay supplies -- so the diff reports the
    baselines as stale when they are correct, and ``--write`` would replace
    good baselines with a world the task never serves.
    """
    compose = task_dir / "environment" / "docker-compose.yaml"
    if not compose.is_file():
        return None
    text = compose.read_text()
    m = re.search(r'COMPLEXMCP_WORLD_DATA:\s*"?([^"\s]+)"?', text)
    if not m:
        return None
    target = m.group(1)
    # find the bind whose target is that container path: "<src>:<target>:ro"
    m2 = re.search(r'-\s*([^\s:]+):' + re.escape(target) + r'(?::[a-z,]+)?\s', text)
    if not m2:
        return None
    return (compose.parent / m2.group(1)).resolve()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task_dir", type=Path)
    ap.add_argument("--write", action="store_true", help="rewrite the baselines in place")
    a = ap.parse_args(argv)

    # Resolved before the chdir below, or every later path would be read
    # relative to services/light-servers instead of the task bundle.
    tests = a.task_dir.resolve() / "tests"
    oracle_path = tests / "oracle.json"
    if not oracle_path.is_file():
        print(f"[rederive] {oracle_path} not found", file=sys.stderr)
        return 2
    oracle = json.loads(oracle_path.read_text())
    seed = int(oracle.get("seed", 42))
    apps = list(oracle.get("apps") or [])

    os.environ["COMPLEXMCP_SEED"] = str(seed)
    os.environ["COMPLEXMCP_SEED_MODE"] = "seed"
    _wd = _world_data_dir(a.task_dir.resolve())
    if _wd and _wd.is_dir():
        os.environ["COMPLEXMCP_WORLD_DATA"] = str(_wd)
        print(f"[rederive] task uses the world_data overlay: {_wd}")
    else:
        os.environ.pop("COMPLEXMCP_WORLD_DATA", None)
    os.environ["ENABLED_SERVERS"] = ",".join(apps)

    os.chdir(LIGHT_SERVERS)
    sys.path.insert(0, str(LIGHT_SERVERS))

    old_env, gt_env = {}, {}
    for app in apps:
        old_env[app] = _dump(_build(app, seed))
        gt_session = _build(app, seed)
        _apply_oracle(gt_session, app, (oracle.get("oracle") or {}).get(app, []))
        gt_env[app] = _dump(gt_session)

    print(f"[rederive] old_env {_counts(old_env)}")
    print(f"[rederive] gt_env  {_counts(gt_env)}")

    agreed = True
    for name, env in (("old_env.json", old_env), ("gt_env.json", gt_env)):
        dest = tests / name
        blob = json.dumps(env, indent=2, default=str)
        if dest.is_file():
            agreed &= _report(name, env, json.loads(dest.read_text()))
        if a.write:
            dest.write_text(blob + "\n")
            print(f"[rederive] wrote {dest}")

    if not agreed and not a.write:
        print("[rederive] the committed baselines do not describe the world the "
              "servers now serve; a correct run would be graded against a world "
              "that no longer exists.")

    if not a.write:
        print("[rederive] dry run; pass --write to update the baselines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
