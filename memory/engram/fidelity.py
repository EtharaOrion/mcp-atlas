"""Fidelity: Phase 1 step 8c reference-fidelity memory writer.

Per `trinity/ENGRAM.md` Phase 1 step 8c, invariant E20, and Phase 2
step 7a:

- Maintain `memory/fidelity.yaml`, an append-only registry keyed by
  `task_hash`, recording for every emulation-bearing task only the
  fidelity facts that arrive already signed inside a CFER attestation
  envelope: `real_upstream_identity`, `real_upstream_version_digest`,
  `real_upstream_score`, and the per-class `divergence_summary`.
- ENGRAM never obtains the real artifact and never replays a suite. It
  remembers and directs over signed evidence alone.
- A verified sub-threshold `real_upstream_score` EXPIRES the affected
  emulation-bearing lever through the standing EXPIRED path and raises
  a coarsened `fidelity:required` escalation for that emulation family.
  It never raises a disposition.
- A greenfield task with no reference-emulation surface adds no row and
  is fully exempt.

The registry is a private ENGRAM surface. Raw fidelity finding text,
divergence taxonomy detail, auditor reasoning, and scores are stripped
from both FORGE_VIEW and CRUCIBLE_VIEW. Only the coarsened flag and the
already-public upstream identity and version reach a slave.

An unsigned or unresolvable fidelity field caps the ledger at BROKEN.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def fold(envelope: dict[str, Any], fidelity_path: Path) -> None:
    """Fold the signed fidelity group of one envelope into memory/fidelity.yaml."""
    raise NotImplementedError(
        "fidelity.fold is scaffolded but not yet implemented; "
        "see trinity/ENGRAM.md Phase 1 step 8c and memory/TODO.md"
    )
