"""Provenance: Phase 1 step 8 digest binding and clean-tree gate.

Per `trinity/ENGRAM.md` Phase 1 step 8 and invariant E8:

- Bind ledger digest, seed digest, proof paths and hashes, git SHA,
  clean bit, approved-scope digest, requirements digest, samples digest,
  and dataset digest.
- `CURRENT` requires external proof signatures, a clean recorded tree,
  no seed drift, and a deterministic recompute.
- A mutable provenance or a dirty tree caps the ledger at BROKEN.

This module is Bucket D. Its accepting path and its rejecting path both
must be proven in the Phase 2 conformance suite per invariant E19.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def bind(parent_root: Path) -> dict[str, Any]:
    """Compute the full provenance binding record for the current run."""
    raise NotImplementedError(
        "provenance.bind is scaffolded but not yet implemented; "
        "see trinity/ENGRAM.md Phase 1 step 8 and memory/TODO.md"
    )
