"""Verifier: DSSE signature verifier against external trust roots.

Per `trinity/ENGRAM.md` invariant E4 and Phase 1 step 4:

- Verify the detached DSSE signature over a CFER attestation envelope.
- Match `signer_identity` against `memory/roots.yaml` by key identity or
  keyless OIDC subject.
- Return verified true only when the signature chains to an external
  trust root the project pinned in scope.

ENGRAM never self-produces a trusted signature. A missing signature, an
unresolvable signer, or a chain break returns verified false and caps
the ledger downstream.

Per invariant E19 the verifier must accept at least one frozen positive
control envelope to prove liveness. A verifier that returns verified
false on every input is inert and caps the ledger at BROKEN.
"""

from __future__ import annotations

from pathlib import Path


def verify(envelope_path: Path, roots_path: Path) -> bool:
    """Verify a single CFER attestation envelope against pinned trust roots.

    Raises NotImplementedError until the accepting path lands. Both the
    accepting branch and the rejecting branch must be proven under
    frozen fixtures in the Phase 2 conformance suite.
    """
    raise NotImplementedError(
        "verifier.verify is scaffolded but not yet implemented; "
        "see trinity/ENGRAM.md invariant E19 and memory/TODO.md"
    )
