"""Positive liveness controls: the accepting half of every Bucket-D instrument.

Per `trinity/ENGRAM.md` invariant E19:

Every required instrument must accept at least one positive control on
frozen fixtures in the run that reports it. A required instrument that
cannot accept any input is inert. Inert is neither a coverage gap nor
fail-closed: it caps the ledger at BROKEN.

The six required Bucket-D instruments each carry a liveness fixture:

- The signature verifier accepts a frozen known-good envelope signed by
  a test trust root and returns verified true.
- The ingestor births exactly one CFER from that envelope.
- The freshener reaches each of ACTIVE, WATCH, EXPIRED at least once
  across its fixtures. RETIRED is human-set only and out of scope here.
- The checkpointer appends a signed tree head over a non-empty ledger.
- The recovery procedure rebuilds the same ledger byte-for-byte from
  the signed envelopes alone.
- The provenance gate binds every required digest and returns CURRENT
  under clean-tree inputs.

At scaffold time every fixture skips with a clear reason. The Phase 2
disposition first-runs at STALE, not BROKEN, per the honest-scaffold
carve-out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engram import freshener


SCAFFOLD_REASON = (
    "E19 liveness controls are scaffolded but not yet implemented; "
    "see trinity/ENGRAM.md invariant E19 and memory/TODO.md"
)


def _freshener_fixture(tmp_path: Path, levers: list[dict]) -> dict:
    """Write a frozen ledger + config and return the freshener state vector.

    The freshener is a pure function of these bytes, so this is a real
    accepting-path control on frozen fixtures, not a mock."""
    ledger = tmp_path / "ledger.yaml"
    config = tmp_path / "freshness.yaml"
    ledger.write_text(json.dumps({"levers": levers}), encoding="utf-8")
    config.write_text(json.dumps({"freshness_horizon_days": 90}), encoding="utf-8")
    return freshener.compute_state_vector(ledger, config)


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_verifier_accepts_positive_control() -> None:
    """Verifier must return verified true for a frozen known-good envelope."""
    raise NotImplementedError


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_ingestor_births_one_cfer_from_positive_control() -> None:
    """Ingestor must birth exactly one CFER from the frozen positive-control envelope."""
    raise NotImplementedError


def test_freshener_reaches_active_state(tmp_path: Path) -> None:
    """Freshener must reach ACTIVE at least once across its fixtures."""
    sv = _freshener_fixture(tmp_path, [
        {"id": "lever-active", "fresh": True, "verified": True,
         "below_defeat_floor": True},
    ])
    assert sv["lever-active"]["state"] == "ACTIVE"


def test_freshener_reaches_watch_state(tmp_path: Path) -> None:
    """Freshener must reach WATCH at least once across its fixtures."""
    sv = _freshener_fixture(tmp_path, [
        {"id": "lever-watch", "fresh": True, "verified": True,
         "below_defeat_floor": True, "narrowed": True},
    ])
    assert sv["lever-watch"]["state"] == "WATCH"


def test_freshener_reaches_expired_state(tmp_path: Path) -> None:
    """Freshener must reach EXPIRED at least once across its fixtures."""
    sv = _freshener_fixture(tmp_path, [
        {"id": "lever-expired", "over_horizon": True},
    ])
    assert sv["lever-expired"]["state"] == "EXPIRED"


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_checkpoint_and_recovery_round_trip() -> None:
    """Checkpointer and recovery must round-trip a non-empty ledger byte-for-byte."""
    raise NotImplementedError


@pytest.mark.skip(reason=SCAFFOLD_REASON)
def test_provenance_accepts_clean_tree() -> None:
    """Provenance gate must return CURRENT for a clean tree with every digest bound."""
    raise NotImplementedError
