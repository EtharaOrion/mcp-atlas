"""Recovery: Phase 1 step 8a byte-identical ledger recovery procedure.

Per `trinity/ENGRAM.md` Phase 1 step 8a, Phase 2 step 4a, and invariant E17:

- Rebuild the entire ledger and its checkpoint chain from the set of
  signed CFER envelopes alone.
- Every CFER is independently signed, and every checkpoint is a
  deterministic Merkle recompute over those envelopes.
- Recovery that does not reproduce the latest signed tree head
  byte-for-byte caps the ledger at BROKEN.

Per invariant E19 the recovery procedure must round-trip a non-empty
ledger byte-for-byte with the checkpointer to prove liveness. The
Phase 2 conformance suite exercises this both ways.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def rebuild(proofs_dir: Path, roots_path: Path) -> dict[str, Any]:
    """Rebuild the ledger and checkpoint chain from signed envelopes alone.

    Returns a dict carrying the rebuilt ledger bytes and the rebuilt
    checkpoint chain bytes for byte-identity comparison against on-disk
    state.
    """
    raise NotImplementedError(
        "recovery.rebuild is scaffolded but not yet implemented; "
        "see trinity/ENGRAM.md invariant E17 and memory/TODO.md"
    )
