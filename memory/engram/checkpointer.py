"""Checkpointer: Phase 1 step 8a signed Merkle checkpoint log writer.

Per `trinity/ENGRAM.md` Phase 1 step 8a and invariant E17:

- After every ingest, compute a Merkle tree over the canonical bytes of
  each appended CFER envelope in ledger order.
- Append a signed tree head to `memory/checkpoints.yaml` carrying the
  prior root, the new root, the leaf count, the ingest timestamp, and a
  detached signature over the head from a trust root in `memory/roots.yaml`.
- A tree head whose signature does not verify, whose prior root does not
  chain to the last accepted head, or whose recomputed root does not
  match the recorded root caps the ledger at BROKEN.
- The multi-operator witness network is deferred behind this log per
  invariant E17 and never required for CURRENT on day one.

Per invariant E19 the checkpointer must round-trip a non-empty ledger
byte-for-byte with the recovery procedure to prove liveness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def append_head(ledger_path: Path, checkpoints_path: Path, roots_path: Path) -> dict[str, Any]:
    """Append one signed Merkle tree head to memory/checkpoints.yaml."""
    raise NotImplementedError(
        "checkpointer.append_head is scaffolded but not yet implemented; "
        "see trinity/ENGRAM.md Phase 1 step 8a and memory/TODO.md"
    )
