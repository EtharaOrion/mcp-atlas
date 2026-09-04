# Corpus Additions — Remaining Changes

> **All three changes are implemented.** The mount is wired, the batch
> fingerprint covers additions, and validation runs on preflight. `task_hash`
> changed for both bundles — see the decision section at the bottom.
>
> Status now: `python -m pytest services/light-servers/tests scripts/tests -q`
> → **115 passed, 5 skipped** (was 100 passed, 4 skipped).
>
> One guard was added beyond the spec: a row missing a field that *every*
> existing corpus row carries is refused at boot. Without it a partial row
> passed validation and then raised `KeyError: 'body'` inside the app's cook
> step — i.e. inside `login`, which is exactly the runtime failure I2 forbids.

The corpus-additions layer is built and tested. What is **not** done is the
wiring that lets a real task run actually use it, and two guards that keep a
resumed batch honest.

Status as of this document: `python -m pytest services/light-servers/tests
scripts/tests -q` → **100 passed, 4 skipped**.

---

## 1. Already built — do not re-do

| Piece | Where | Evidence |
|---|---|---|
| Registry, caching **strings only** (invariant I1) | `software/utils/corpus_registry.py:44` — `_CACHE: Dict[str, str]` | `test_cache_holds_only_strings`, `test_two_loads_share_nothing` |
| No write path in the module | same | `test_no_write_api` |
| Boot refusals — seedless, `COMPLEXMCP_WORLD_DATA` conflict, `world.json`, missing/empty mount, bad rows, missing canary | `corpus_registry._refuse_unless_additions_can_take_effect()`, `validate_all()`, `_require_canary()` | 11 `test_refuses_*` tests |
| Boot gate wired before serving (invariant I2) | `server_main.py:40-44` → `corpus_boot.main()` | `test_boot_gate_exits_nonzero_and_names_the_app` |
| All corpus reads routed through the registry | 0 remaining `yaml.safe_load` under `software/Light*/` | `test_no_direct_corpus_reads`, `test_every_app_corpus_loads_through_registry` |
| Baseline re-derivation | `scripts/rederive_env.py`, `scripts/qc_task.sh` | `tests/test_grading_baselines.py` |
| The three required properties | — | `test_additions_are_appended_after_existing_rows`, `test_restart_discards_additions`, `test_corpus_bytes_unchanged_by_a_full_build`, `test_inert_when_unused` |
| `.gitignore` entry | `.gitignore:12` — `corpus_additions/` | — |

Relevant constants: `ADDITIONS_ENV = "COMPLEXMCP_CORPUS_ADDITIONS"`
(`corpus_registry.py:40`). Host-side entry point: `corpus_boot.validate(software_dir=None)`
returns the list of apps that received additions; `corpus_boot.main()` returns
`0` / `2` and prints `[corpus-additions] REFUSING TO START: …` on stderr.

---

## Change 1 — Wire the mount *(blocking: the feature is currently unreachable)*

### The problem

Neither task bundle's `docker-compose.yaml` mounts an additions directory, and
`ADDITIONS_DIR` appears nowhere in `scripts/run_task.sh`. `additions_dir()`
reads `COMPLEXMCP_CORPUS_ADDITIONS`, which nothing sets inside the container.

So every piece above is inert in a real Harbor run — `validate_all()` returns
`[]` at line 1 and the stock world is served. The tests pass because they set
the env var themselves.

### The change

**a. `tasks/<task>/environment/docker-compose.yaml`**, in the `light-servers`
service:

```yaml
    environment:
      COMPLEXMCP_CORPUS_ADDITIONS: "/corpus_additions"
    volumes:
      - workspace_data:/workspace
      - ${ADDITIONS_DIR:?ADDITIONS_DIR must be set by scripts/run_task.sh}:/corpus_additions:ro
```

**Use `:?`, never `:-`.** The existing line 35 —
`${SCORING_DIR:-../../../services/scoring}` — is the anti-pattern: with a
fallback, an unset variable resolves to a relative path, Docker **silently
creates the missing host directory and mounts it empty**, and the server boots
clean serving the stock world. `:?` makes compose fail instead.

**b. `scripts/run_task.sh`** — pin an absolute path near the other derived vars
(`REPO` at `:34`, `SLUG` at `:54`, `OUTPUT_DIR` at `:60`):

```sh
ADDITIONS_DIR="${ADDITIONS_DIR:-$REPO/corpus_additions/$SLUG}"
mkdir -p "$ADDITIONS_DIR"        # empty dir = feature off, which validate_all handles
export ADDITIONS_DIR
```

Keyed by `$SLUG`, not global. `--concurrency` fans out across *different tasks*
against one repo checkout; a global `corpus_additions/LightGmail.yaml` would be
picked up by every concurrent task using LightGmail, including ones that never
asked for it.

Placed **outside** the bundle so `task_hash` is unaffected — see the decision
below.

### Exit gate

Boot a task with one addition present and assert `[corpus-additions] applied to:
LightGmail` appears in the environment-build log. Then unset `ADDITIONS_DIR` and
assert compose **fails** rather than mounting empty.

---

## Change 2 — Teach the batch fingerprint about additions

### The problem

`scripts/run_batch.py:398-405`:

```python
fingerprint = ckpt.fingerprint_of({
    "agent": args.agent, "model": args.model, "n": args.n, "at": args.at,
    "build_mult": args.build_mult, "output_dir": ...,
    "tasks": sorted(t.name for t in tasks),   # names, not content
    "harness_commit": _git_commit(),
})
```

Additions are absent. `harness_commit` does not cover them either, because
`.gitignore:12` keeps `corpus_additions/` out of git.

**Failure:** pause a batch (`run_batch.py:498` — first signal finishes the
current step and stops), edit an additions file, resume. Early units ran against
one world and later units against another, and both roll into the same
`passk_summary.json`. There is no signal anywhere.

This is a narrower case of an existing gap — the fingerprint hashes task *names*,
so editing `instruction.md` or `gt_env.json` mid-batch is equally invisible.
Additions make it far likelier, because they are the input you are *expected*
to edit between runs.

### The change

- Add a key to that dict: the SHA-256 of every additions file for every task in
  the batch, sorted by path, missing-file included as an explicit empty marker
  (so "additions removed" is a change too, not a silent match).
- Record the same hash in `run_config.json` / `summary.json` so a delivered
  trajectory states which world it ran against.
- When `--force` bypasses `FingerprintMismatch`, write a loud `events.jsonl`
  entry naming what differed.

### Exit gate

A test in `scripts/tests/test_run_batch.py`: plan a batch, edit an additions
file, resume → `FingerprintMismatch`. Then `--force` → resumes **and** an
`events.jsonl` entry records the override.

---

## Change 3 — Validate additions in preflight, not only at container boot

### The problem

`scripts/run_task.sh:124-136` (`stage_preflight`) only checks that Docker is up
and pulls the image. It validates nothing about the task.

`corpus_boot.main()` therefore runs only inside the container — which is inside
`harbor_run`, the step `scripts/checkpoint.py` describes as *"never re-run once
any evidence on disk; minutes-and-money"*. A typo, a duplicate id, or a missing
canary header burns an environment build before it is caught.

### The change

Call the same validator host-side from `stage_preflight`:

```sh
COMPLEXMCP_CORPUS_ADDITIONS="$ADDITIONS_DIR" \
COMPLEXMCP_SEED_MODE=seed \
  python3 services/light-servers/software/utils/corpus_boot.py \
  || { echo "[run_task] corpus additions rejected — fix before the agent phase" >&2; exit 4; }
```

One validator, two call sites. `stage_preflight` is idempotent and free, so
`run_batch.py` re-runs it on every resume at no cost. The container-boot gate
stays exactly as it is — it is the authority; this is just an early mirror.

> `corpus_boot.validate()` defaults `software_dir` to `_APP_ROOT / "software"`,
> which resolves to the container layout. Host-side invocation must pass
> `services/light-servers/software` explicitly, or `corpus_boot` needs to
> resolve it relative to its own file. Check this before writing the call.

### Exit gate

Put a duplicate id in an additions file, run `--stage preflight`, assert exit 4
and a message naming the app and key — with **no** container started.

---

## Decision made — where additions live vs. `task_hash`

**Resolved: both compose files were hand-patched.** `task_hash` has changed for
`draft-side-table-lot-price` and `bull-street-lot-expense-claim`. Everything in
this document is now implemented.

Two premises in the original framing did not survive checking, and the options
narrowed accordingly:

- **`memory/crucible_view.yaml` does not exist.** `find . -name 'crucible_view*'`
  returns nothing; `memory/` holds `README.md`, `TODO.md`, `capabilities.yaml`,
  `engram/`, `pyproject.toml`, `tests/`. The `task_artifact_hashes` →
  `bytes_moved_since_canary_issue` binding is not verifiable from inside this
  repo, so whatever tracks it lives elsewhere.
- **The adapter cannot regenerate these bundles.** `adapters/mcp_atlas/adapter.py:611`
  writes `DOCKER_COMPOSE_TEMPLATE`, which emits `main` + `mcp-server` from a
  generic image with a sandbox port. It has no `light-servers` service and no
  `ENABLED_SERVERS`. The two complex-MCP bundles were not produced by it and
  cannot be round-tripped through it — that option would have meant writing a
  new generator, for the same hash change.

| Option | Status |
|---|---|
| Edit the compose files, re-issue `task_hash` | **Taken.** ~8 lines per bundle |
| ~~Regenerate through `adapters/mcp_atlas/adapter.py`~~ | Unavailable — wrong template, see above |
| Ship additions support only on *new* bundles | Rejected: the two current tasks would never use the feature |

A fourth route was investigated and set aside: harbor's
`extra_docker_compose_paths` (`harbor/environments/definition.py:15`) layers an
override compose file from outside the bundle, which would add the mount with no
bundle-byte change at all. No CLI flag exposes it — `harbor run` cannot set it —
so `stage_harbor` would have to stop shelling out and drive harbor's Python API
instead, concentrating new risk on the one step that is never re-run. Worth
revisiting if the hash change ever becomes the blocker it was assumed to be.

---

## Also worth fixing while here — pre-existing, unrelated

`tasks/*/environment/docker-compose.yaml:32` claims:

> *"scripts/run_task.sh pins SCORING_DIR to an absolute path"*

`SCORING_DIR` appears nowhere in `scripts/run_task.sh`. The pinning was never
written; compose has always fallen through to
`../../../services/scoring`. It happens to resolve correctly for the current
bundle depth, so nothing has broken yet — but the comment documents a guard that
does not exist, and the comment itself explains why that guard matters (a wrong
depth mounts `/harness/scoring` **empty** and the grader vanishes, scoring the
trial 0 with one line in verifier stdout).

Fix it in the same pass as Change 1, since `ADDITIONS_DIR` is establishing
exactly the pattern `SCORING_DIR` was supposed to have.

---

## Order

```
Change 1  →  feature becomes reachable at all         (blocked on the task_hash decision)
Change 2  →  resumed batches cannot silently split worlds
Change 3  →  failures land on the cheap step, not the paid one
```

Change 1 is a prerequisite for any real run. Change 2 matters the moment
batches are used — and `output/_batches/` is still empty, so no batch has run
yet and the window to land it before it can hurt is open. Change 3 only saves
time and money.
