"""Recon: read-only Phase 0 inventory of trinity surfaces.

Per `trinity/ENGRAM.md` Phase 0 steps 1 through 8:

- Detect whether `memory/ledger.yaml` and the `memory/` harness already
  exist and mark UPDATE versus fresh runs.
- Re-sample `requirements/`, `samples/`, and `dataset/` and record their
  digests.
- Compute the work differential against the prior ledger.
- Inventory trinity surfaces, evidence sources, and trust roots.
- Classify the ledger shape and derive the required-instrument set.
- Emit `memory/scope.yaml` and stop before writing ledger files.

This module is Bucket D. It never mints CFERs, never promotes a lever,
and never raises a disposition on its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run(parent_root: Path) -> dict[str, Any]:
    """Recon Phase 0 against the given parent project root.

    Returns the candidate scope structure that becomes `memory/scope.yaml`.
    Raises NotImplementedError until the accepting path lands.
    """
    raise NotImplementedError(
        "recon.run is scaffolded but not yet implemented; "
        "see trinity/ENGRAM.md Phase 0 and memory/TODO.md"
    )
