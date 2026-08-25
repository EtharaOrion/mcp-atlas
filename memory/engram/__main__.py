"""CLI entry for the ENGRAM harness.

Wires the `engram` command declared in pyproject.toml to per-phase
subcommands. Each subcommand defers to its contract phase per
`trinity/ENGRAM.md`.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Dispatch the top-level engram CLI.

    Real subcommands will land as later Phase 0 through Phase 2 code
    upgrades. At scaffold time every accepting path raises
    NotImplementedError per invariant E19.
    """
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        _print_usage()
        return 2
    raise NotImplementedError(
        "engram CLI subcommands are scaffolded but not yet implemented; "
        "see memory/TODO.md and memory/capabilities.yaml bucket_d_status"
    )


def _print_usage() -> None:
    print(
        "engram <subcommand>\n"
        "  scope     run Phase 0 discovery, write memory/scope.yaml\n"
        "  scaffold  run Phase 1 after Phase 0.5 approval\n"
        "  prove     run Phase 2 deterministic prove of the ledger\n"
        "  genesis   run Phase G to birth a new knowledge repository\n"
        "  research  run integrated Phase R corpus refresh\n"
        "  scribe    run Phase S paper authoring against CURRENT ledger\n",
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
