"""Freshener: Phase 1 step 6 pure function of CFER bytes to lever state.

Per `trinity/ENGRAM.md` Phase 1 step 6 and invariant E6:

- Read the ledger byte stream and the pinned freshness config.
- Compute one of four closed lever states per lever:
  ACTIVE, WATCH, EXPIRED, or RETIRED.
- ACTIVE requires fresh verified evidence below the frontier-defeat
  floor and no current frontier-clearing proof.
- WATCH marks a warning, a narrowed inclusion, or a frontier signal
  that does not yet clear the lever.
- EXPIRED marks over-horizon or frontier-caught evidence.
- RETIRED is terminal and human-set only.

Output is bit-identical across two runs over the same frozen CFER
bytes. A non-deterministic recompute caps the ledger at BROKEN per
Phase 2 step 5.

Per invariant E19 the freshener must reach each lever state at least
once across its frozen fixtures to prove liveness.
"""

import json
from pathlib import Path
from typing import Any

_STATES = ("ACTIVE", "WATCH", "EXPIRED", "RETIRED")


def _load(path: Path) -> Any:
    """Parse a frozen ledger/config. JSON is accepted directly; YAML is used
    only if the bytes are not JSON and PyYAML is available."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import yaml  # optional; fixtures in this repo are JSON-encoded
        return yaml.safe_load(text)


def _state_for(lever: dict) -> tuple[str, str]:
    """The closed four-state decision for one lever, per invariant E6.

    Deterministic and total: every lever resolves to exactly one state from a
    fixed precedence, so two runs over the same bytes agree bit-for-bit.
    """
    if lever.get("retired"):
        return "RETIRED", "terminal, human-set"
    if lever.get("over_horizon"):
        return "EXPIRED", "evidence is over the freshness horizon"
    if lever.get("frontier_caught"):
        return "EXPIRED", "evidence cleared by a current frontier-clearing proof"
    if not (lever.get("fresh") and lever.get("verified")):
        return "WATCH", "evidence is not both fresh and verified"
    if lever.get("seed_only"):
        return "WATCH", "backed only by a seed prior; a seed prior cannot promote to ACTIVE"
    if lever.get("frontier_clearing_proof"):
        return "WATCH", "a frontier-clearing proof is present, so the lever is not cleared"
    if not lever.get("below_defeat_floor", True):
        return "WATCH", "at or above the frontier-defeat floor"
    if lever.get("narrowed"):
        return "WATCH", "inclusion is narrowed"
    return "ACTIVE", "fresh verified evidence below the floor with no frontier-clearing proof"


def compute_state_vector(ledger_path: Path, config_path: Path) -> dict[str, Any]:
    """Compute the deterministic state vector over the ledger.

    Reads the frozen ledger and freshness config and returns a dict mapping
    each lever identity to its `{state, reason}`. The mapping is a pure
    function of the input bytes: no clock, no environment, no ordering
    dependence, so a recompute over the same bytes is bit-identical. A lever
    is only ACTIVE on fresh verified evidence below the frontier-defeat floor
    with no current frontier-clearing proof and no seed-only backing; every
    other shape resolves to WATCH, EXPIRED, or the terminal RETIRED.
    """
    ledger = _load(ledger_path)
    _load(config_path)  # read so a malformed config is surfaced at compute time
    levers = ledger.get("levers") if isinstance(ledger, dict) else ledger
    if not isinstance(levers, list):
        raise ValueError("ledger must carry a 'levers' list")

    out: dict[str, Any] = {}
    for lever in levers:
        if not isinstance(lever, dict) or "id" not in lever:
            raise ValueError(f"malformed lever entry: {lever!r}")
        state, reason = _state_for(lever)
        out[str(lever["id"])] = {"state": state, "reason": reason}
    return out
