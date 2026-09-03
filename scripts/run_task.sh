#!/usr/bin/env bash
# Run one mcp-atlas Harbor task end-to-end and emit the per-task output/ tree
# (same layout complex-mcp's --layout harbor writer produces).
#
#   scripts/run_task.sh tasks/xenon-atomic-cube                 # claude-code + opus-5 (defaults)
#   MODEL=claude-sonnet-4-6 N=3 scripts/run_task.sh tasks/foo   # 3 attempts, pass@k over them
#   AGENT=oracle scripts/run_task.sh tasks/foo                  # oracle gate
#   COPY_TO=/some/dir scripts/run_task.sh tasks/foo           # optional extra mirror
#
#   scripts/run_task.sh --stage reshape tasks/foo               # one stage only
#
# Env overrides: AGENT (claude-code) MODEL (claude-opus-5) N (1) JOB (<task slug>)
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
SETUP_MULT="${SETUP_MULT:-3}"   # agent-setup timeout multiplier (360s base -> 18m)
AGENT_HEADROOM_ENABLED="${AGENT_HEADROOM_ENABLED:-false}"  # agent-path compression: OFF
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

# The reshaped output dir is NOT always output/<bundle-dir>. harbor_to_output.py
# names it from task.toml's `name` (last path segment), falling back to the
# bundle dir -- so tasks/Input_1 with name="complexmcp/larkmoor-depot-false-
# alarm-attribution" reshapes into output/larkmoor-depot-false-alarm-attribution
# while Harbor's raw job stays in output/Input_1. $JOB is right for the raw job;
# everything that reads the reshaped tree has to use this instead. Matches the
# converter's own regex so the two cannot disagree.
resolve_out_slug() {
  local name=""
  if [ -f "$TASK/task.toml" ]; then
    name="$(grep -m1 -E '^[[:space:]]*name[[:space:]]*=[[:space:]]*"' "$TASK/task.toml" 2>/dev/null \
            | sed -E 's/^[[:space:]]*name[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/')"
  fi
  name="${name##*/}"
  [ -n "$name" ] || name="$SLUG"
  printf '%s\n' "$name"
}
OUT_SLUG="$(resolve_out_slug)"

TRAJ_DIR="$OUTPUT_DIR/$OUT_SLUG/trajectory"
STATE_FILE="$OUTPUT_DIR/$JOB/.run_state.json"
# Kept outside output/<job>/ on purpose: harbor may wipe the job dir wholesale,
# which would take a stash living inside it with it.
STASH_DIR="$OUTPUT_DIR/.stash/$JOB"

state_get() {  # state_get <key> -> value on stdout, empty if absent
  [ -f "$STATE_FILE" ] || return 0
  # `or ""` would fold a real 0 into "absent", and run_offset is 0 on every
  # first run -- callers then fell back to counting Run_* dirs and aimed one
  # run too high. Only None/missing may read as empty.
  python3 -c 'import json,sys
try:
    v = json.load(open(sys.argv[1])).get(sys.argv[2])
    print("" if v is None else v)
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
  # SETUP_MULT multiplies Harbor's agent-setup timeout (base 360s). Setup is
  # `apt-get install curl procps` followed by
  # `curl downloads.claude.ai/.../bootstrap.sh | bash`, so it is network-bound
  # and unrelated to how long the task itself takes. A slow mirror or a cold
  # CDN blows the default and the trial dies as AgentSetupTimeoutError with an
  # empty /logs/agent -- which reads like an agent that produced nothing rather
  # than an agent that never started. Observed on a run that had succeeded
  # three times prior with no task change.
  # Must precede harbor: it exports ANTHROPIC_BASE_URL, which harbor's
  # claude_code agent reads from this environment and forwards into the
  # container (empty values are dropped, so a failed proxy start is a no-op).
  route_agent_through_proxy
  local args=(run -y --path "$TASK" --agent "$AGENT" --jobs-dir "$OUTPUT_DIR" --job-name "$JOB" \
              --environment-build-timeout-multiplier "$BUILD_MULT" \
              --agent-setup-timeout-multiplier "$SETUP_MULT" --n-attempts "$N")
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

# Grade the rubric channel on the host, between harbor and reshape.
#
# The in-container judge cannot do it: task.toml pins JUDGE_MODEL=gpt-5.6-sol,
# and codex does not exist in python:3.12-slim. Putting one there would mean
# mounting this machine's ChatGPT credential into the container the agent just
# ran in under bypassPermissions, and Harbor cannot isolate the verifier from
# that container either -- environment_mode='separate' restarts light-servers
# clean and destroys the world the state channel reads. So the container grades
# everything that needs the live world, and the rubric is graded here.
#
# Runs before stage_reshape so harbor_to_output.py copies the corrected reward
# rather than the rubric-less one. Checkpointed, because a resume must not spend
# judge quota re-grading a trial it already graded.
# ---------------------------------------------------------------- agent proxy
# Route the AGENT's traffic through the Headroom proxy, so its prompts are
# compressed too. OFF unless AGENT_HEADROOM_ENABLED=true.
#
# Nothing is started here. `headroom proxy` already runs on this host (it is
# what a Claude Code session points ANTHROPIC_BASE_URL at), so this stage only
# re-points the CONTAINER at it. The whole job is fixing the host part of the
# URL: the value inherited from the session is http://127.0.0.1:<port>, and
# inside the container 127.0.0.1 is the container -- which is exactly why the
# unset at the top of this script exists. host.docker.internal is the same
# proxy as seen from inside.
#
# Health-checked first: pointing the agent at a dead port turns every turn into
# "API Error: Connection refused", which reads as the agent refusing the task
# rather than as infrastructure. If the proxy does not answer we leave
# ANTHROPIC_BASE_URL unset and run direct, exactly as before.
HEADROOM_PROXY_PORT="${HEADROOM_PROXY_PORT:-8787}"

route_agent_through_proxy() {
  [ "$AGENT_HEADROOM_ENABLED" = "true" ] || return 0
  if ! curl -sf -m 3 "http://127.0.0.1:$HEADROOM_PROXY_PORT/health" >/dev/null 2>&1; then
    echo "[run_task] no headroom proxy on :$HEADROOM_PROXY_PORT; running direct" >&2
    echo "[run_task]   start one with: headroom proxy --port $HEADROOM_PROXY_PORT" >&2
    return 0
  fi
  export ANTHROPIC_BASE_URL="http://host.docker.internal:$HEADROOM_PROXY_PORT"
  echo "[run_task] agent routed through headroom proxy ($ANTHROPIC_BASE_URL)"
  echo "[run_task]   NOTE: setting ANTHROPIC_BASE_URL makes harbor pin every model"
  echo "[run_task]   alias (sonnet/opus/haiku/subagent) to $MODEL -- claude_code.py:1358."
}

stage_host_rubric() {
  [ "$(state_get host_rubric_done)" = "1" ] && { echo "[run_task] host rubric already graded; skipping"; return 0; }
  local trial
  # Trial dirs are named after the TASK slug, not the job: JOB=Input_1_oracle
  # still produces Input_1__PMNhXaa. Globbing on "$JOB__*" therefore found
  # nothing whenever JOB was overridden, and the pass skipped itself with
  # "no trial dir" while the run looked fine.
  trial="$(find "$OUTPUT_DIR/$JOB" -maxdepth 1 -type d -name "*__*" 2>/dev/null | head -1)"
  if [ -z "$trial" ]; then
    echo "[run_task] no trial dir under $OUTPUT_DIR/$JOB; skipping host rubric" >&2
    return 0
  fi
  # FALLBACK, NOT OVERRIDE. Only grade here when the in-container judge did
  # not produce a rubric.
  #
  # Input_1 pins JUDGE_MODEL=gpt-5.6-sol so its container judge fails preflight
  # and defers to this pass. The other bundles pin nothing, and since
  # rubric_judge_cli now resolves to the Claude transport when codex is absent,
  # their container judge SUCCEEDS. Running unconditionally would then grade
  # every one of them twice -- Claude in the container, codex here, second
  # writer wins -- for double the cost and artifacts that disagree with the
  # score. Set FORCE_HOST_RUBRIC=1 to re-grade deliberately.
  if [ "${FORCE_HOST_RUBRIC:-0}" != "1" ] \
     && [ -s "$trial/verifier/rubric_breakdown.json" ]; then
    echo "[run_task] rubric already graded in-container; skipping host pass"
    state_put host_rubric_done 1
    return 0
  fi
  local py; py="$REPO/.venv/bin/python"; [ -x "$py" ] || py=python3
  if "$py" "$REPO/scripts/host_rubric_pass.py" --trial "$trial" --task "$TASK"; then
    state_put host_rubric_done 1
  else
    # A failed rubric is not a failed run: Channel A and the state channel are
    # already graded and still worth reporting. Leave the checkpoint unset so a
    # rerun retries this without repeating the agent phase.
    echo "[run_task] host rubric pass failed; rubric channel stays UNSCORED" >&2
  fi
}

stage_reshape() {
  stage_host_rubric
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
  # The .env may live above the harness when it is vendored into a larger
  # workspace, so search upward the way finance_reporter.py does.
  if [ -z "${ODOO_URL:-}" ]; then
    local d="$REPO"
    while [ -n "$d" ] && [ "$d" != "/" ]; do
      if [ -f "$d/.env" ]; then
        ODOO_URL="$(grep -E '^ODOO_URL=' "$d/.env" | tail -1 | cut -d= -f2- \
                    | sed 's/[[:space:]]*#.*$//' | tr -d '[:space:]' || true)"
        [ -n "$ODOO_URL" ] && break
      fi
      d="$(dirname "$d")"
    done
  fi
  if [ -z "${ODOO_URL:-}" ]; then
    echo "[finance] WARNING: ODOO_URL unset (no .env at or above $REPO) — usage NOT reported" >&2
    return 0
  fi

  local offset; offset="$(state_get run_offset)"
  [ -n "$offset" ] || offset="$(resolve_run_offset)"
  # Prefer the reshaped tree; fall back to the job dir for bundles whose
  # task.toml name already matches their directory.
  local run_dir="$OUTPUT_DIR/$OUT_SLUG/trajectory/Run_$((offset+1))"
  if [ ! -d "$run_dir" ] && [ -d "$OUTPUT_DIR/$JOB/trajectory/Run_$((offset+1))" ]; then
    run_dir="$OUTPUT_DIR/$JOB/trajectory/Run_$((offset+1))"
  fi
  python3 scripts/finance_reporter.py \
    --run-dir "$run_dir" \
    --skip-if-reported \
    --task-id "$OUT_SLUG" || echo "[finance] WARNING: reporting failed (non-fatal)"
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
