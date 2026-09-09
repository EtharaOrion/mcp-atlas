#!/usr/bin/env python3
"""Backfill: attribute Claude Code's self-authored events to the model.

`harbor_to_output.strip_client_authored_tree` does this at reshape time. Runs
reshaped before that existed still carry `"model": "<synthetic>"` and
`"isSynthetic": true` in every copy of their agent records -- the stream, the
per-run trajectory.json, and Claude Code's own session transcripts. This walks
an output tree and applies the same rewrite to all of them.

The model is resolved per run, never assumed: report.json, then config.json's
agent.model_name, then the `trajectories/<model>/` segment that .raw layouts
encode it in. A run whose model will not resolve is reported and skipped -- a
wrong model name in a trajectory is worse than a label that says nothing.

    python3 scripts/relabel_agent_logs.py output
    python3 scripts/relabel_agent_logs.py output --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools" / "delivery"))
from harbor_to_output import (  # noqa: E402
    CLIENT_AUTHORED_MODEL,
    strip_client_authored_markers,
)

# A trial still running is still appending to its stream; rewriting the file
# under it truncates whatever the agent writes next. Recent mtime means "in
# flight" and is left alone. A settled run never trips this.
LIVE_WINDOW_SEC = 120

SUFFIXES = (".jsonl", ".json", ".txt", ".log")


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def resolve_model(f: Path) -> str:
    for anc in list(f.parents)[:6]:
        for name, pick in (("report.json", lambda d: d.get("model")),
                           ("config.json", lambda d: (d.get("agent") or {}).get("model_name"))):
            doc = _load(anc / name)
            if isinstance(doc, dict):
                got = pick(doc)
                if isinstance(got, str) and got and got != CLIENT_AUTHORED_MODEL:
                    return got
    parts = f.parts
    if "trajectories" in parts:
        i = parts.index("trajectories")
        if i + 1 < len(parts):
            return parts[i + 1]
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help=f"rewrite even files touched in the last {LIVE_WINDOW_SEC}s")
    a = ap.parse_args(argv)

    total, files, skipped, live = 0, 0, [], []
    for f in sorted(a.root.rglob("*")):
        if not f.is_file() or f.suffix not in SUFFIXES:
            continue
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n_markers = raw.count(CLIENT_AUTHORED_MODEL) + raw.count('"isSynthetic"')
        if not n_markers:
            continue
        if time.time() - f.stat().st_mtime < LIVE_WINDOW_SEC and not a.force:
            live.append(f)
            continue
        model = resolve_model(f)
        if not model:
            skipped.append(f)
            continue
        if a.dry_run:
            print(f"would attribute {n_markers:3d} -> {model!r}  {f}")
            total += n_markers
        else:
            n = strip_client_authored_markers(f, model)
            print(f"attributed {n:3d} line(s) -> {model!r}  {f}")
            total += n
        files += 1

    for f in live:
        print(f"SKIPPED (in flight): {f}", file=sys.stderr)
    for f in skipped:
        print(f"SKIPPED (model unresolvable): {f}", file=sys.stderr)
    print(f"\n{'would change' if a.dry_run else 'changed'} {total} across {files} file(s); "
          f"{len(skipped)} unresolvable, {len(live)} in flight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
