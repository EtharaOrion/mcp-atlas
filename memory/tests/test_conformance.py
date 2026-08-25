"""Conformance suite: the deterministic Phase 2 gate.

Per `trinity/ENGRAM.md` Phase 2 step 2 and invariant E19:

Every required Bucket-D instrument must demonstrate both halves of its
decision on frozen fixtures in the run that reports it. This module
holds the conformance-side controls and pairs with test_negative_controls
and test_liveness_controls_E19.

At scaffold time every test skips with a clear reason and every
required Bucket-D instrument carries `implemented: false` and
`liveness_proven: false` in memory/capabilities.yaml. The Phase 2
disposition first-runs at STALE, not BROKEN, per the honest-scaffold
carve-out.
"""

from __future__ import annotations

import pytest


SCAFFOLD_REASON = (
    "conformance suite is scaffolded but not yet implemented; "
    "see trinity/ENGRAM.md Phase 2 step 2 and memory/TODO.md"
)


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_projector_strips_forbidden_fields() -> None:
    """FORGE_VIEW and CRUCIBLE_VIEW must carry no named forbidden field."""
    raise NotImplementedError


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_freshener_is_bit_identical() -> None:
    """Freshener output over frozen CFER bytes must match byte-for-byte across two runs."""
    raise NotImplementedError


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_provenance_binds_all_digests() -> None:
    """Provenance binding must cover ledger, seed, proofs, git SHA, and every scope digest."""
    raise NotImplementedError


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_checkpoint_chain_verifies() -> None:
    """Every signed tree head must chain to its predecessor and verify against a trust root."""
    raise NotImplementedError
