#!/usr/bin/env bash
# Run one mcp-atlas Harbor task end-to-end and emit the per-task output/ tree
# (same layout complex-mcp's --layout harbor writer produces).
#
#   scripts/run_task.sh tasks/xenon-atomic-cube                 # claude-code + opus-4-8 (defaults)
#   MODEL=claude-sonnet-4-6 N=3 scripts/run_task.sh tasks/foo   # 3 attempts, pass@k over them
#   AGENT=oracle scripts/run_task.sh tasks/foo                  # oracle gate
#   COPY_TO=/some/dir scripts/run_task.sh tasks/foo           # optional extra mirror
#
#   scripts/run_task.sh --stage reshape tasks/foo               # one stage only
#
# Env overrides: AGENT (claude-code) MODEL (claude-opus-4-8) N (1) JOB (<task slug>)
#                OUTPUT_DIR (<repo>/output) COPY_TO (unset) BUILD_MULT (3) AT (1)
#                STAGE (all) RUN_OFFSET (auto)
#
# Stages. The default STAGE=all runs the four below in order, which is the
# original one-shot behaviour. They are separable because their costs differ by
# orders of magnitude: the agent phase takes minutes and real money, reshaping
# takes seconds, and reporting is one HTTP call. A crash between them must not
# re-run the agent, so scripts/run_batch.py drives them one at a time and
# checkpoints in between.
#
#   preflight  auth, docker, image pull                     (idempotent)
#   harbor     harbor run -> output/<job>/                  (NOT idempotent: makes a trial)
#   reshape    harbor_to_output.py -> trajectory/Run_N/      (idempotent)
#   finance    finance_reporter.py -> Odoo                  (NOT idempotent: external POST)
#
# State that crosses a stage boundary (which Run_N this invocation owns, where
# earlier runs were stashed) is written to output/<job>/.run_state.json so a
# later stage in a separate process can pick it up.
set -euo pipefail
# Clear anything in the caller's environment that would redirect the agent's
# `claude` CLI away from the API. Running this script from inside a Claude Code
# session exports ANTHROPIC_BASE_URL=http://127.0.0.1:<port> for that session's
# own proxy; inherited into the task container, 127.0.0.1 is the container and
# nothing listens there, so every agent turn dies with
# "API Error: Connection refused (ConnectionRefused)" -- an infrastructure
# failure that reads exactly like the agent refusing the task.
# CLAUDE_CODE_OAUTH_TOKEN is deliberately NOT cleared: it is what the run
# authenticates with, and the verifier needs it too.
unset AWS_BEARER_TOKEN_BEDROCK 2>/dev/null || true
unset ANTHROPIC_BASE_URL ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN 2>/dev/null || true
unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SSE_PORT 2>/dev/null || true
unset CLAUDE_CODE_MESSAGING_SOCKET CLAUDE_CODE_MESSAGING_TOKEN 2>/dev/null || true

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

STAGE="${STAGE:-all}"
TASK=""
while [ $# -gt 0 ]; do
  case "$1" in
    --stage)   STAGE="${2:?--stage needs a value}"; shift 2;;
    --stage=*) STAGE="${1#*=}"; shift;;
    -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *)         TASK="$1"; shift;;
  esac
done

TASK="${TASK:?usage: scripts/run_task.sh [--stage all|preflight|harbor|reshape|finance] <task-dir>}"
[ -f "$TASK/task.toml" ] || { echo "not a task dir (no task.toml): $TASK" >&2; exit 2; }
case "$STAGE" in
  all|preflight|harbor|reshape|finance) ;;
  *) echo "unknown stage: $STAGE (want all|preflight|harbor|reshape|finance)" >&2; exit 2;;
esac
SLUG="$(basename "$TASK")"

AGENT="${AGENT:-claude-code}"
MODEL="${MODEL:-claude-opus-4-8}"
N="${N:-1}"
BUILD_MULT="${BUILD_MULT:-3}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO/output}"
AT="${AT:-1}"
JOB="${JOB:-$SLUG}"   # job dir == output/<task>/ (reshaped in place by the converter)

# World data appended to the light-servers corpus at boot, mounted read-only
# into the light-servers container. Absolute, because compose resolves relative
# bind sources against the compose file's directory, not the caller's cwd -- and
# a wrong relative path does not error: Docker creates the missing host dir and
# mounts it EMPTY, which boots clean and serves the stock world.
#
# Keyed by $SLUG, never global. `run_batch.py --concurrency` fans out across
# different tasks against one checkout, so a shared corpus_additions/ would hand
# LightGmail rows to every concurrent task that happens to use LightGmail,
# including the ones that never asked for them.
#
# An empty or absent directory means the feature is off; corpus_boot treats that
# as "not configured" and the stock world is served. Kept outside the bundle so
# task_hash is unaffected.
ADDITIONS_DIR="${ADDITIONS_DIR:-$REPO/corpus_additions/$SLUG}"
mkdir -p "$ADDITIONS_DIR"
export ADDITIONS_DIR

# The env var the container reads, set ONLY when the host directory actually
# holds additions. This is what keeps "feature off" and "mount mis-resolved to
# empty" distinguishable, which they otherwise are not:
#
#   dir has *.yaml  -> COMPLEXMCP_CORPUS_ADDITIONS=/corpus_additions, and an
#                      empty mount inside the container is then a hard refusal,
#                      because we know the files were there on the host.
#   dir is empty    -> env var empty, validate_all() returns [] at line 1, stock
#                      world served. No refusal, because nothing was asked for.
#
# Setting the env var unconditionally would make every ordinary run refuse to
# boot, since the default directory is empty.
if compgen -G "$ADDITIONS_DIR/*.yaml" >/dev/null 2>&1; then
  CORPUS_ADDITIONS_MOUNT="/corpus_additions"
  echo "[run_task] corpus additions: $(ls "$ADDITIONS_DIR"/*.yaml | wc -l | tr -d ' ') file(s) from $ADDITIONS_DIR"
else
  CORPUS_ADDITIONS_MOUNT=""
fi
export CORPUS_ADDITIONS_MOUNT

# The absolute pin the compose comment has always claimed existed. Without it,
# compose falls through to ${SCORING_DIR:-../../../services/scoring}, which is
# correct only for bundles at exactly the current depth; at any other depth
# Docker creates the missing directory, mounts /harness/scoring EMPTY, and the
# collect hook dies with "can't open file" -- a trial scored 0 with the agent's
# work intact. Refuse instead of mounting a directory that isn't the grader.
SCORING_DIR="${SCORING_DIR:-$REPO/services/scoring}"
if [ ! -f "$SCORING_DIR/collect_artifacts.py" ]; then
  echo "[run_task] SCORING_DIR does not hold the grader (no collect_artifacts.py): $SCORING_DIR" >&2
  exit 2
fi
export SCORING_DIR

TRAJ_DIR="$OUTPUT_DIR/$JOB/trajectory"
STATE_FILE="$OUTPUT_DIR/$JOB/.run_state.json"
# Kept outside output/<job>/ on purpose: harbor may wipe the job dir wholesale,
# which would take a stash living inside it with it.
STASH_DIR="$OUTPUT_DIR/.stash/$JOB"

state_get() {  # state_get <key> -> value on stdout, empty if absent
  [ -f "$STATE_FILE" ] || return 0
  python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get(sys.argv[2], "") or "")
except Exception:
    pass' "$STATE_FILE" "$1"
}

state_put() {  # state_put <key> <value>
  mkdir -p "$(dirname "$STATE_FILE")"
  python3 -c 'import json,os,sys
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    doc = json.load(open(path))
except Exception:
    doc = {}
doc[key] = int(value) if value.lstrip("-").isdigit() else value
tmp = path + ".tmp"
open(tmp, "w").write(json.dumps(doc, indent=2) + "\n")
os.replace(tmp, path)' "$STATE_FILE" "$1" "$2"
}

# Which Run_N this invocation owns. An explicit RUN_OFFSET (what run_batch.py
# passes) wins, because the driver already decided the numbering; otherwise
# count what is on disk, which is what a bare run_task.sh has always done.
resolve_run_offset() {
  if [ -n "${RUN_OFFSET:-}" ]; then echo "$RUN_OFFSET"; return; fi
  local last=""
  if [ -d "$TRAJ_DIR" ]; then
    last="$(ls "$TRAJ_DIR" 2>/dev/null | grep -E '^Run_[0-9]+$' | sed 's/Run_//' | sort -n | tail -1 || true)"
  fi
  echo "${last:-0}"
}

# --- stages -------------------------------------------------------------------

# Harbor's agent and the in-container judge both need a token. Every stage
# resolves this, not just preflight: stages run as separate processes now, so an
# export in one is gone by the time the next starts, and harbor aborts up front
# on a missing [verifier.env] variable.
resolve_auth() {
  [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && return 0
  [ -n "${ANTHROPIC_API_KEY:-}" ] && return 0
  TOKEN="$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null \
           | python3 -c 'import sys,json; print(json.load(sys.stdin)["claudeAiOauth"]["accessToken"])' 2>/dev/null || true)"
  if [ -n "$TOKEN" ]; then
    export CLAUDE_CODE_OAUTH_TOKEN="$TOKEN"
    echo "[run_task] using Claude Code OAuth token from keychain"
  else
    echo "[run_task] WARNING: no CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY — agent + judge will fail auth" >&2
  fi
}

stage_preflight() {
  if ! docker info >/dev/null 2>&1; then
    echo "[run_task] docker not running — starting OrbStack/Docker"
    open -a OrbStack 2>/dev/null || open -a Docker 2>/dev/null || true
    for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
    docker info >/dev/null 2>&1 || { echo "[run_task] docker still down" >&2; exit 3; }
  fi
  IMAGE="$(grep -E '^image *= *"' "$TASK/task.toml" 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)".*/\1/' || true)"
  if [ -n "$IMAGE" ] && ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "[run_task] pulling $IMAGE"
    docker pull "$IMAGE"
  fi

  # Validate corpus additions HERE, on the cheap idempotent step, rather than
  # letting the container-boot gate be the first to see them. corpus_boot runs
  # inside harbor_run, which checkpoint.py describes as "never re-run once any
  # evidence is on disk; minutes-and-money" -- so a typo, a duplicate id or a
  # missing canary header would otherwise burn an environment build before
  # anyone hears about it.
  #
  # One validator, two call sites. The container gate stays the authority; this
  # is an early mirror, and stage_preflight is free, so run_batch.py re-runs it
  # on every resume at no cost.
  if [ -n "${CORPUS_ADDITIONS_MOUNT:-}" ]; then
    _cb="$REPO/services/light-servers/software/utils/corpus_boot.py"
    # corpus_boot resolves software_dir from its own file location, so it is
    # correct on the host and in the container alike -- no argument needed.
    _py=""
    for _cand in "$REPO/.venv/bin/python" python3 python; do
      if command -v "$_cand" >/dev/null 2>&1 && "$_cand" -c 'import yaml' >/dev/null 2>&1; then
        _py="$_cand"; break
      fi
    done
    if [ -z "$_py" ]; then
      # Cannot validate is NOT the same as invalid: refusing the run because the
      # host lacks pyyaml would be worse than deferring to the container gate.
      echo "[run_task] WARNING: no python with pyyaml on the host; corpus additions" >&2
      echo "[run_task]          will only be validated at container boot" >&2
    else
      # Mirror the container's own env so the host check is exactly as strict:
      # ENABLED_SERVERS is what makes "additions for an app this task never
      # starts" a refusal rather than a silent no-op, and the compose file is
      # where the host can learn it.
      _compose="$TASK/environment/docker-compose.yaml"
      _enabled="$(sed -n 's/.*ENABLED_SERVERS: *"\([^"]*\)".*/\1/p' "$_compose" 2>/dev/null | head -1)"
      _seedmode="$(sed -n 's/.*COMPLEXMCP_SEED_MODE: *"\([^"]*\)".*/\1/p' "$_compose" 2>/dev/null | head -1)"
      COMPLEXMCP_CORPUS_ADDITIONS="$ADDITIONS_DIR" \
      COMPLEXMCP_SEED_MODE="${_seedmode:-seed}" \
      ENABLED_SERVERS="$_enabled" \
      COMPLEXMCP_WORLD_DATA="" \
        "$_py" "$_cb" \
        || { echo "[run_task] corpus additions rejected — fix before the agent phase" >&2; exit 4; }
    fi
  fi
}

stage_harbor() {
  local offset; offset="$(resolve_run_offset)"
  state_put slug "$SLUG"
  state_put job "$JOB"
  state_put run_offset "$offset"

  # Preserve earlier Run_* dirs: harbor owns output/<job>/ and will happily
  # clear it, and those runs are other units' trajectories.
  if [ -d "$TRAJ_DIR" ]; then
    mkdir -p "$STASH_DIR"
    cp -r "$TRAJ_DIR"/Run_* "$STASH_DIR/" 2>/dev/null || true
    state_put stash_dir "$STASH_DIR"
  fi

  rm -f "$OUTPUT_DIR/$JOB/lock.json"
  local args=(run -y --path "$TASK" --agent "$AGENT" --jobs-dir "$OUTPUT_DIR" --job-name "$JOB" \
              --environment-build-timeout-multiplier "$BUILD_MULT" --n-attempts "$N")
  [ "$AGENT" != "oracle" ] && args+=(--model "$MODEL")
  echo "[run_task] harbor ${args[*]}"
  HARBOR_OUTPUT_OFF=1 command harbor "${args[@]}" \
    || echo "[run_task] harbor exited non-zero; reshaping whatever landed" >&2
  state_put harbor_done 1
}

stage_reshape() {
  local offset; offset="$(state_get run_offset)"
  [ -n "$offset" ] || offset="$(resolve_run_offset)"
  local conv=(python3 scripts/harbor_to_output.py "$OUTPUT_DIR/$JOB" \
              --output-dir "$OUTPUT_DIR" --at "$AT" --run-offset "$offset")
  [ -n "${COPY_TO:-}" ] && conv+=(--copy-to "$COPY_TO")
  "${conv[@]}"

  # Put back the Run_* dirs harbor may have wiped. Never overwrite: the run
  # this invocation just produced is the newer truth for its own Run_N.
  local stash; stash="$(state_get stash_dir)"
  [ -n "$stash" ] || stash="$STASH_DIR"
  if [ -d "$stash" ]; then
    mkdir -p "$TRAJ_DIR"
    for run_dir in "$stash"/Run_*; do
      [ -d "$run_dir" ] || continue
      run_name="$(basename "$run_dir")"
      [ -d "$TRAJ_DIR/$run_name" ] || cp -r "$run_dir" "$TRAJ_DIR/$run_name"
    done
    rm -rf "$stash"
  fi
  state_put run_dir "$OUTPUT_DIR/$JOB/trajectory/Run_$((offset+1))"
}

# finance API: report trajectory usage (after the runs are done).
# Skips itself when ODOO_URL is unset; never fails the task run.
# ODOO_URL normally lives in .env, which this script does not source, so read it
# from there when the environment doesn't already provide it.
stage_finance() {
  if [ -z "${ODOO_URL:-}" ] && [ -f .env ]; then
    ODOO_URL="$(grep -E '^ODOO_URL=' .env | tail -1 | cut -d= -f2- \
                | sed 's/[[:space:]]*#.*$//' | tr -d '[:space:]' || true)"
  fi
  [ -n "${ODOO_URL:-}" ] || { echo "[finance] ODOO_URL unset — skipping"; return 0; }

  local offset; offset="$(state_get run_offset)"
  [ -n "$offset" ] || offset="$(resolve_run_offset)"
  python3 scripts/finance_reporter.py \
    --run-dir "$OUTPUT_DIR/$JOB/trajectory/Run_$((offset+1))" \
    --skip-if-reported \
    --task-id "$SLUG" || echo "[finance] WARNING: reporting failed (non-fatal)"
}

# --- dispatch -----------------------------------------------------------------

resolve_auth

case "$STAGE" in
  preflight) stage_preflight ;;
  harbor)    stage_harbor ;;
  reshape)   stage_reshape ;;
  finance)   stage_finance ;;
  all)       stage_preflight; stage_harbor; stage_reshape; stage_finance
             echo "[run_task] done → $OUTPUT_DIR/$SLUG" ;;
esac
