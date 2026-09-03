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
#   preflight  auth, docker, image build/pull               (idempotent)
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
MODEL="${MODEL:-claude-opus-5}"
N="${N:-1}"
BUILD_MULT="${BUILD_MULT:-3}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO/output}"
AT="${AT:-auto}"   # pass@k ks for the reshaper; auto = every k from 1..N runs
JOB="${JOB:-$SLUG}"   # job dir == output/<task>/ (reshaped in place by the converter)

# Extended-thinking capture. `adaptive` + `summarized` is the only request shape
# the API returns readable thinking text for on Opus 4.8/5-family models —
# `enabled`+budget_tokens comes back as signature-only blocks with empty text
# (measured 2026-09-02; see THINKING_FIX.md). Set THINKING="" to skip the flags
# entirely (e.g. for an older pinned CLI without --thinking support).
THINKING="${THINKING:-adaptive}"                       # enabled|adaptive|disabled|""
THINKING_DISPLAY="${THINKING_DISPLAY:-summarized}"     # summarized|omitted|""

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

# --- images -------------------------------------------------------------------
# Nothing below ever asks the operator to have run `docker pull` or
# `make build-light-servers` first. Preflight is the cheap idempotent stage
# run_batch.py re-runs on every resume, so it is the right place to make the
# world match what the bundle declares.

# A python that can parse YAML. The repo venv has pyyaml; a bare system python3
# usually does not. Empty when nothing on the host can.
python_with_yaml() {
  local c
  for c in "$REPO/.venv/bin/python" python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import yaml' >/dev/null 2>&1; then
      echo "$c"; return 0
    fi
  done
}

# Images the bundle needs that NOTHING in the run will produce on its own: a
# compose service carrying an `image:` and no `build:`. `main` has a build:
# section, so compose builds it and it is deliberately not listed here.
compose_unbuilt_images() {
  local compose="$1" py
  [ -f "$compose" ] || return 0
  py="$(python_with_yaml)"
  if [ -n "$py" ]; then
    "$py" -c '
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1])) or {}
for svc in (doc.get("services") or {}).values():
    if isinstance(svc, dict) and svc.get("image") and not svc.get("build"):
        print(svc["image"])
' "$compose" && return 0
  fi
  # No pyyaml anywhere on the host. Fall back to a structural scan: service keys
  # sit at exactly two spaces and their fields deeper, which holds for every
  # bundle in this repo. Depth is what keeps `depends_on:`'s nested
  # `light-servers:` from being read as a service of its own.
  awk '
    /^services:[[:space:]]*$/ { in_s = 1; next }
    in_s && /^[^[:space:]#]/  { in_s = 0 }
    in_s && /^  [A-Za-z0-9_.-]+:[[:space:]]*$/ {
      if (img != "" && !built) print img
      img = ""; built = 0; next
    }
    in_s && /^[[:space:]]+build:/ { built = 1 }
    in_s && /^[[:space:]]+image:[[:space:]]*/ {
      v = $0
      sub(/^[[:space:]]+image:[[:space:]]*/, "", v)
      sub(/[[:space:]]*#.*$/, "", v)
      gsub(/["'"'"']/, "", v)
      img = v
    }
    END { if (img != "" && !built) print img }
  ' "$compose"
}

# How to obtain an image the local daemon does not have. Images built out of
# this checkout are in NO registry -- `docker pull light-servers:latest` 404s --
# so a pull-only preflight cannot fix the one image every bundle here needs.
# Anything not named is treated as a registry image and pulled.
image_build_context() {
  case "${1%%:*}" in
    light-servers)     echo "$REPO/services/light-servers" ;;
    agent-environment) echo "$REPO/services/agent-environment" ;;
  esac
}

# Make one image usable, however it has to be obtained. Never asks the operator
# to have run `docker pull` or `make build-light-servers` first, which is what a
# fresh clone otherwise required: light-servers:latest is declared only in
# compose, with no build: section, so nothing in the run produces it and the
# compose up inside harbor_run dies on
# "pull access denied for light-servers, repository does not exist" -- minutes
# into the one stage that must never be re-run.
#
# For images built out of this checkout the refresh is an unconditional
# `docker build`, not a timestamp comparison, because there is nothing on the
# image to compare against: BuildKit does NOT advance .Created when every layer
# is cached (the config blob is byte-identical, so it is reused as-is). An
# mtime-vs-.Created check therefore never converges -- it reports stale,
# rebuilds, sees the same old .Created, and rebuilds again on every single run.
# BuildKit's own cache already answers the real question exactly, and answers it
# in about a second when nothing changed.
ensure_image() {
  local img="$1" ctx
  ctx="$(image_build_context "$img")"

  # Registry image: presence is the entire question.
  if [ -z "$ctx" ]; then
    docker image inspect "$img" >/dev/null 2>&1 && return 0
    echo "[run_task] $img is not present locally — pulling"
    docker pull "$img" || { echo "[run_task] failed to pull $img" >&2; exit 3; }
    return 0
  fi

  # First build on this machine -- the fresh-clone case. Minutes, with nothing
  # cached, so let the build print its own progress.
  if ! docker image inspect "$img" >/dev/null 2>&1; then
    echo "[run_task] $img is not present locally — building from $ctx"
    docker build -t "$img" "$ctx" \
      || { echo "[run_task] failed to build $img from $ctx" >&2; exit 3; }
    return 0
  fi

  # Present. Rebuild anyway so edits under $ctx reach the run: compose pins the
  # image by tag, so without this they simply do not, and nothing errors -- the
  # container boots clean, serves the previous world, and the agent is graded
  # against a bundle that no longer exists on disk. Quiet, because the common
  # case is fully cached and prints one line.
  [ -z "${SKIP_IMAGE_REFRESH:-}" ] || return 0
  docker build -q -t "$img" "$ctx" >/dev/null \
    || { echo "[run_task] failed to refresh $img from $ctx" >&2; exit 3; }
}

stage_preflight() {
  if ! docker info >/dev/null 2>&1; then
    echo "[run_task] docker not running — starting OrbStack/Docker"
    open -a OrbStack 2>/dev/null || open -a Docker 2>/dev/null || true
    for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
    docker info >/dev/null 2>&1 || { echo "[run_task] docker still down" >&2; exit 3; }
  fi
  # Every image this bundle needs, from both places one can be declared: the
  # (rare) top-level `image =` in task.toml, and the compose services that pin
  # an image with no build: section. No task.toml in this repo sets the former,
  # which is why the task.toml-only grep this replaces pulled nothing, ever --
  # while light-servers:latest, the image every bundle here actually depends on,
  # is declared only in compose and had to be built by hand before each run.
  for _img in \
    "$(grep -E '^image *= *"' "$TASK/task.toml" 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)".*/\1/' || true)" \
    $(compose_unbuilt_images "$TASK/environment/docker-compose.yaml")
  do
    [ -n "$_img" ] || continue
    ensure_image "$_img"
  done

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
  if [ "$AGENT" = "claude-code" ]; then
    [ -n "$THINKING" ] && args+=(--ak "thinking=$THINKING")
    [ -n "$THINKING_DISPLAY" ] && args+=(--ak "thinking_display=$THINKING_DISPLAY")
  fi
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
  # Relative to the job dir this state file sits in — keeps host-local paths
  # out of everything the pipeline writes (informational only, never read back).
  state_put run_dir "trajectory/Run_$((offset+1))"
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
