# DIRECTIVE.md

Root executive report of the ENGRAM instrument for the target parent root `harness/` (mcp-atlas). This run was invoked with this repository as its operating parent root under `trinity/ENGRAM.md`. The Trinity freshness gate fired before the resume preflight and before any phase work, and it failed closed, so this report carries the staleness entry as its only finding and no phase work was performed.

## Executive summary

🔴 BROKEN. ⛔ The Trinity freshness gate hard-blocked this run: the operating parent root `harness/` vendors no `trinity/` submodule, so the checked-out contract commit cannot be resolved against the upstream `main` tip and freshness cannot be established. A freshness that cannot be established is stale by definition, and a stale `trinity/` is a hard block. No resume preflight, no legacy-layout migration, no feedback capture, and no phase work ran. The run resumes only after the human vendors `trinity/` in this root at the latest upstream `main` tip, or redirects the invocation at a parent root that carries it.

## Disposition

BROKEN

## Findings

- ⛔ `trinity-staleness` (dated 2026-09-04T06:26:24Z): the operating parent root `harness/` carries no `trinity/` submodule and no `.gitmodules` entry for one; commit `e20c420` ("chore: remove .gitmodules file and associated submodule references") removed all submodule references from this repository. Checked-out trinity commit: absent. Fetched upstream `main` tip of `git@github.com:Ethara-Ai/trinity.git`: `ae28fe9f15a0dab5d96abc11e8f508057f3b30c6` (fetched 2026-09-04T06:26:24Z via the sibling checkout at the yuji parent root, since this root configures no trinity remote). Absent versus any tip is unresolvable, therefore stale, therefore a hard block.

## Coverage gaps

- ⚠️ `trinity-staleness`: named blocking coverage gap per the Trinity freshness gate; see Findings. Resumption requires the human to add `trinity/` to this root as a git submodule pinned at the fetched `main` tip `ae28fe9f15a0dab5d96abc11e8f508057f3b30c6`, or to invoke ENGRAM from a parent root that already vendors a fresh `trinity/`.

## Escalations

None.

## Flag legend

- ✅ pass
- ⚠️ coverage gap, stale claim, or unverified claim
- ⛔ critical or blocking defect
- 🟢 CURRENT
- 🟡 STALE
- 🔴 BROKEN
