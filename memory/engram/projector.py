"""Projector: pure ledger projection to FORGE_VIEW and CRUCIBLE_VIEW.

Per `trinity/ENGRAM.md` Firewall section and invariant E16:

The rule that FORGE and CRUCIBLE never talk is a function, not a
promise. This module is the function. It reads the ledger bytes and
emits exactly two computed projections. Neither slave may read the raw
ledger or `memory/proofs/`.

FORGE_VIEW carries: lever identity, category, state; allowed archetype
pressure and the frontier-defeat floor; signed pilot failure aggregates
as counts and bounds; freshness horizon and measurement dates; public
lineage identifiers; the coarsened `fidelity:required` flag with the
already-public upstream identity and version; the coarsened
`calibration:required` flag.

CRUCIBLE_VIEW carries: task artifact hashes and claimed scope with
`upstream_provenance`; provenance manifests and proof digests;
the ENGRAM-bound contamination corpus snapshot digest when declared;
checker metadata by lane, carrier class, and binding identity;
integrity priorities and required-instrument escalation flags including
`fidelity:required` and `calibration:required`.

Named forbidden fields are stripped by name. Conformance fails closed
if any forbidden field survives into the wrong view. CRUCIBLE-originated
`invalid_at` reasons are coarsened to `lever:saturated`, `checker:broken`,
or `task:blocked` before entering FORGE_VIEW.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def project_forge_view(ledger_path: Path, out_path: Path) -> dict[str, Any]:
    """Emit memory/forge_view.yaml as a pure function of ledger bytes."""
    raise NotImplementedError(
        "projector.project_forge_view is scaffolded but not yet implemented; "
        "see trinity/ENGRAM.md Firewall and memory/TODO.md"
    )


def project_crucible_view(ledger_path: Path, out_path: Path) -> dict[str, Any]:
    """Emit memory/crucible_view.yaml as a pure function of ledger bytes."""
    raise NotImplementedError(
        "projector.project_crucible_view is scaffolded but not yet implemented; "
        "see trinity/ENGRAM.md Firewall and memory/TODO.md"
    )
