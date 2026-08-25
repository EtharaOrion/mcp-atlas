# ENGRAM augmentation backlog

GENERATED SECTION. DO NOT HAND-EDIT.

Source of truth: `memory/capabilities.yaml` for capability and instrument rows, and the named gap set below for coverage-gap rows. This file is emitted from those blocks. Any drift between this file and `memory/capabilities.yaml` fails closed.

Scope: the yuji harness submodule at `harness/`. This backlog is the submodule's own and is disjoint from the parent-root `memory/TODO.md`, which ENGRAM regenerates separately from the parent capability block.

Regenerated: 2026-08-24T18:05:00Z under `trinity/ENGRAM.md` Phase G step 9. No approved scope digest is in force here, because Phase 0.5 has never been signed for this submodule as parent root.

## Bucket-D instruments not yet liveness proven

Every row below is honestly `implemented: false`, which is unbuilt machinery and a coverage gap rather than inertness. A row flipping to `implemented: true` without a passing positive control in the same run is theater and caps the ledger at BROKEN with reason `deterministic_lane_inert`.

| Instrument | Module | Bytes present | Implemented | Liveness proven | Module to build or repair | Current fail-closed consequence |
| --- | --- | --- | --- | --- | --- | --- |
| ingestor | `engram/ingestor.py` | yes | no | no | `memory/engram/ingestor.py` accepting path | No CFER can be born, so no lever can reach ACTIVE. |
| verifier | `engram/verifier.py` | yes | no | no | `memory/engram/verifier.py` accepting path | No DSSE signature of any predicate type can verify. E4 closes CURRENT. |
| freshener | `engram/freshener.py` | yes | no | no | `memory/engram/freshener.py` accepting path | No lever state is computable and the double-run determinism check cannot execute. |
| checkpointer | `engram/checkpointer.py` | yes | no | no | `memory/engram/checkpointer.py` accepting path | No signed tree head can be appended over the ledger. |
| recovery | `engram/recovery.py` | yes | no | no | `memory/engram/recovery.py` accepting path | The ledger, supersessions, and screening standing cannot be rebuilt byte-identically. |
| provenance | `engram/provenance.py` | yes | no | no | `memory/engram/provenance.py` accepting path | Proof digest closure and the clean-tree binding cannot be enforced. |

The projector at `memory/engram/projector.py` carries no `bucket_d_status` row and is not a seventh instrument, but it also raises `NotImplementedError`. No projection is rendered here, and this submodule exposes neither `FORGE_VIEW` nor `CRUCIBLE_VIEW` to any peer.

## Capabilities declared but not implemented

None. Every capability sits at `default`: `identity_attestation`, `witness_network`, `contamination`, `orthogonality`, `autonomous_gates`. A capability at `default` is the contract's baseline posture rather than an unfulfilled promise, so it owes no backlog row. A flip to `declared` without an objective byte-level definition is decorative and never raises a disposition, and a flip to `implemented` with absent defining bytes caps the ledger at BROKEN.

## Coverage gaps

| Gap | What is missing | Where to repair | Current fail-closed consequence |
| --- | --- | --- | --- |
| `engram-harness-unimplemented` | Every accepting path in `memory/engram/` raises `NotImplementedError`. | `memory/engram/` | No phase past Phase 0 can run against this submodule as parent root. Disposition cannot exceed STALE. |
| `todo-generator-unbuilt` | This file was emitted by the same derivation rule the harness owes, because `memory/engram/reporter.py` is unimplemented and cannot emit it. | `memory/engram/reporter.py` | The generated-from-code guarantee is asserted rather than enforced, so drift between this file and `memory/capabilities.yaml` is not machine-detected. |
| `submodule-scope-absent` | No `memory/scope.yaml` and no `memory/approval` exist here, so Phase 0.5 has never been signed for this submodule as parent root. | `memory/scope.yaml`, `memory/approval` | Phase 1 refuses to write any ledger surface here. This is correct fail-closed behavior, not a defect. |
| `submodule-roots-absent` | No `memory/roots.yaml` exists here, so no external trust root is pinned for this submodule. | `memory/roots.yaml` | No signature could be verified even if the verifier were implemented. |
| `submodule-ledger-absent` | No `memory/ledger.yaml`, `memory/proofs/`, `memory/checkpoints.yaml`, or `memory/sequence.yaml` exists here. | Phase 1 outputs | Zero CFERs. Nothing in this submodule carries a measured difficulty claim. |

## Feedback

None. No `memory/feedback.yaml` exists in this submodule, because no ENGRAM run has ever taken this submodule as its parent root. The invocation that scaffolded this harness is recorded in the parent-root ledger at `memory/feedback.yaml` as `feedback_id: 2`.

## Row counts

Bucket-D instrument rows: 6. Declared-capability rows: 0. Coverage-gap rows: 5. Feedback rows: 0.
