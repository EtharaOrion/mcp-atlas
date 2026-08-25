"""Negative controls: the rejecting half of every Bucket-D instrument.

Per `trinity/ENGRAM.md` invariant E19:

Every required instrument must reject every negative control. A
verifier that returns verified true on a tampered signature, an
ingestor that births a CFER from an envelope with a mismatched
predicate type, or a freshener that promotes a lever with no signed
evidence is a broken instrument and caps the ledger at BROKEN.

Negative controls alone are not sufficient. They pair with
test_liveness_controls_E19 to prove both halves of every decision.
"""

from __future__ import annotations

import pytest


SCAFFOLD_REASON = (
    "negative controls are scaffolded but not yet implemented; "
    "see trinity/ENGRAM.md invariant E19 and memory/TODO.md"
)


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_verifier_rejects_bad_signature() -> None:
    """Verifier must return verified false on a tampered envelope."""
    raise NotImplementedError


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_verifier_rejects_unknown_signer() -> None:
    """Verifier must return verified false when signer_identity does not match a trust root."""
    raise NotImplementedError


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_ingestor_rejects_wrong_predicate_type() -> None:
    """Ingestor must birth no CFER for an envelope whose predicateType is not engram.cfer/v1."""
    raise NotImplementedError


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_freshener_rejects_seed_only_active() -> None:
    """Freshener must never promote a lever backed only by a seed prior."""
    raise NotImplementedError


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_freshener_rejects_frontier_caught_active() -> None:
    """Freshener must expire any lever cleared by a current frontier-clearing proof."""
    raise NotImplementedError


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_checkpointer_rejects_chain_break() -> None:
    """Checkpointer must refuse a tree head whose prior_root does not chain to the last accepted head."""
    raise NotImplementedError
