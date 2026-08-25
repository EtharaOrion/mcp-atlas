"""Canary: Phase 1 step 8b canary derivation and cross-task registry.

Per `trinity/ENGRAM.md` Phase 1 step 8b:

- The per-bundle canary tokens both slaves use are a pure function of
  the `task_hash` pinned in the CFER envelope.
- ENGRAM defines the derivation root and binds it to the canonical task
  bytes. A token that does not derive from the bound `task_hash` is invalid.
- Maintain `memory/canary.yaml`, an append-only registry of issued
  tokens keyed by `task_hash`.
- A token issued for one bundle reappearing in any other bundle is
  detectable cross-task contamination that only the memory daemon spans.
- A leaked canary or a cross-task token reuse is a measured integrity
  failure that EXPIRES the affected lever and never raises a disposition.

The registry is a private ENGRAM surface. Canary bytes are stripped
from both FORGE_VIEW and CRUCIBLE_VIEW by name, and only the derivation
root binding reaches a slave.

The optional `contamination` capability uses the same surface: the
training-corpus snapshot digest is ENGRAM-bound and its outcomes are
recorded here, keyed by `task_hash`.
"""

from __future__ import annotations

from pathlib import Path


def derive_token(task_hash: str, derivation_root: bytes) -> str:
    """Derive the canary token for a task from the bound derivation root."""
    raise NotImplementedError(
        "canary.derive_token is scaffolded but not yet implemented; "
        "see trinity/ENGRAM.md Phase 1 step 8b and memory/TODO.md"
    )


def append_issuance(task_hash: str, token: str, registry_path: Path) -> None:
    """Append a token issuance record keyed by task_hash to canary.yaml."""
    raise NotImplementedError(
        "canary.append_issuance is scaffolded but not yet implemented; "
        "see trinity/ENGRAM.md Phase 1 step 8b and memory/TODO.md"
    )
