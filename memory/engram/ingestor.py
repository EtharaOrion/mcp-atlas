"""Ingestor: Phase 1 step 4 CFER envelope ingestor.

Per `trinity/ENGRAM.md` Phase 1 step 4 and the CFER attestation envelope
specification:

- Read every `memory/proofs/*.yaml` on disk.
- Parse each file against the `engram.cfer/v1` predicate schema.
- Confirm the predicate type and resolve every pinned field:
  `cfer_id`, `signer_identity`, `solver_registry_digest`, `task_hash`,
  `checker_hash`, `transcript_hash`, `environment_hash`, `pilot_outcome`,
  `statistical_rule`, `binomial_upper_bound`, `model_cohort`,
  `measured_date`, `signed_at`, `ingested_at`, `validity_interval`, and
  `disposition`.
- Call the DSSE verifier from `engram.verifier` against `memory/roots.yaml`.
- Birth exactly one CFER per isolated lever in a verified proof.
- Append to `memory/ledger.yaml` and never mutate a prior CFER.

A proof that does not parse to the envelope schema, a signature that
does not verify, or a hash that cannot be resolved births no CFER and
caps the ledger at BROKEN per Phase 1 step 4.

Per invariant E19 the ingestor must birth exactly one CFER from a
frozen positive-control envelope to prove liveness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def ingest_all(proofs_dir: Path, roots_path: Path, ledger_path: Path) -> list[dict[str, Any]]:
    """Ingest every envelope under proofs_dir and append CFERs to the ledger.

    Returns the list of newly-birthed CFER records. Raises
    NotImplementedError until the accepting path lands.
    """
    raise NotImplementedError(
        "ingestor.ingest_all is scaffolded but not yet implemented; "
        "see trinity/ENGRAM.md Phase 1 step 4 and memory/TODO.md"
    )
