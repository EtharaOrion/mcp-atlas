"""Calibration: Phase 1 step 8d calibration memory writer.

Per `trinity/ENGRAM.md` Phase 1 step 8d, invariant E21, and Phase 2
step 7b:

- Record calibration facts beside the fidelity facts in
  `memory/fidelity.yaml`, keyed by `task_hash`.
- For every tier-declaring task, fold in only the calibration fields
  that arrive signed inside a CFER envelope: `declared_tier`,
  `cohort_pass_rates`, and `clean_host_reproducible`.
- ENGRAM never rebuilds a bundle, never reruns a pilot, and never
  recomputes a pass rate. It remembers and directs over signed evidence
  alone.
- A verified declared tier that inverts against its signed per-cohort
  pass-rate aggregate beyond the bound calibration margin EXPIRES the
  affected lever through the standing EXPIRED path and raises a
  coarsened `calibration:required` escalation.
- A verified signed clean-host reproducibility failure does the same.
- Neither ever raises a disposition.
- A greenfield task with no declared multi-tier family adds no row and
  is fully exempt.

Calibration facts are a private ENGRAM surface. Raw per-cohort scores,
tier-inversion detail, reproducibility detail, and auditor reasoning
are stripped from both FORGE_VIEW and CRUCIBLE_VIEW. Only the coarsened
`calibration:required` flag reaches a slave.

An unsigned or unresolvable calibration field caps the ledger at BROKEN.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def fold(envelope: dict[str, Any], fidelity_path: Path) -> None:
    """Fold the signed calibration group of one envelope into memory/fidelity.yaml."""
    raise NotImplementedError(
        "calibration.fold is scaffolded but not yet implemented; "
        "see trinity/ENGRAM.md Phase 1 step 8d and memory/TODO.md"
    )
