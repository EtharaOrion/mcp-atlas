# memory/

ENGRAM harness for the yuji harness submodule.

This directory holds the memory daemon scaffolded into this submodule under `trinity/ENGRAM.md` Phase G step 9, which places the `memory/` harness into every submodule of the parent knowledge repository. The master memory daemon lives at the yuji parent project root; this one is its submodule-scoped sibling and never outranks it. The contract is authoritative on every detail. This README is orientation only and never restates the contract.

## What lives here

The harness is a uv Python project. It carries the six required Bucket-D instruments plus the reporting, projection, canary, fidelity, calibration, research, and genesis modules, exactly as the parent harness does.

Code surfaces:

- `engram/` is the Python package.
- `tests/` holds the conformance suite, the negative controls, and the E19 positive liveness controls.

Machine surfaces:

- `capabilities.yaml` carries the per-project opt-in block and the generated `bucket_d_status`.
- `TODO.md` is the generated human projection of `capabilities.yaml` and the named coverage gaps.

Phase G step 9 scaffolds the harness and seeds exactly those two machine surfaces. It does not scaffold `scope.yaml`, `approval`, `ledger.yaml`, `roots.yaml`, `proofs/`, or any other ledger surface, because each of those is the output of a run rather than a part of the harness. Those files land here only if ENGRAM is invoked with this submodule as its parent root and its own Phase 0.5 gate is signed.

## Entry points

Human doors live at the yuji parent project root, not here. Read `.opencode/commands/engram.md` for the instrument, `.opencode/commands/genesis.md` for Phase G, `.opencode/commands/research.md` for corpus refresh, `.opencode/commands/hardness.md` for Phase H, `.opencode/commands/harvest.md` for the harvest lane, and `.opencode/commands/scribe.md` for Phase S. The scope-approval gate lives at `.agents/skills/seal/SKILL.md`.

## Status

This harness is honestly scaffolded. Every required Bucket-D instrument carries `bytes_present: true`, `implemented: false`, and `liveness_proven: false` in `capabilities.yaml`, and every accepting path raises `NotImplementedError`. That is the honest-scaffold case of invariant E19: an instrument that admits it is unbuilt is a coverage gap, never inert theater, so it first-runs at `STALE` and never at `BROKEN`.

No ledger exists here and no CFER has ever been born here. Nothing in this directory carries a measured difficulty claim, and nothing in it feeds the parent ledger, either projection, or any disposition the parent instrument reports.
