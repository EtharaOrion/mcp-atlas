"""ENGRAM package: memory daemon for the yuji harness submodule.

This package implements the required ENGRAM instruments per
`trinity/ENGRAM.md`. The contract is authoritative; this package is
its executable surface.

Module map:

- recon: Phase 0 read-only inventory of trinity surfaces.
- ingestor: Phase 1 step 4 verifier of CFER attestation envelopes.
- verifier: DSSE signature verifier against external trust roots.
- freshener: Phase 1 step 6 pure function of CFER bytes to lever state.
- reporter: Phase 1 step 7 writer of DIRECTIVE.md and freshness.yaml.
- projector: Phase 1 step 7 pure projector for FORGE_VIEW and CRUCIBLE_VIEW.
- provenance: Phase 1 step 8 digest binding and clean-tree gate.
- checkpointer: Phase 1 step 8a signed Merkle checkpoint log writer.
- recovery: Phase 1 step 8a byte-identical ledger recovery procedure.
- canary: Phase 1 step 8b canary derivation and cross-task registry.
- fidelity: Phase 1 step 8c reference-fidelity memory writer.
- calibration: Phase 1 step 8d calibration memory writer.
- researcher: Phase R integrated arXiv and GitHub corpus builder.
- genesis: Phase G project birth and reconciler.

Every accepting path raises NotImplementedError at scaffold time. Real
bytes land in later Phase 0 through Phase 2 iterations, per invariant E19.
"""

__version__ = "0.1.0"

__all__ = [
    "recon",
    "ingestor",
    "verifier",
    "freshener",
    "reporter",
    "projector",
    "provenance",
    "checkpointer",
    "recovery",
    "canary",
    "fidelity",
    "calibration",
    "researcher",
    "genesis",
]
