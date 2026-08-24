#!/usr/bin/env bash
# Run one mcp-atlas Harbor task end-to-end and emit the per-task output/ tree
# (same layout complex-mcp's --layout harbor writer produces).
#
#   scripts/run_task.sh tasks/xenon-atomic-cube                 # claude-code + opus-4-8 (defaults)
#   MODEL=claude-sonnet-4-6 N=3 scripts/run_task.sh tasks/foo   # 3 attempts, pass@k over them
#   AGENT=oracle scripts/run_task.sh tasks/foo                  # oracle gate
#   COPY_TO=/some/dir scripts/run_task.sh tasks/foo           # optional extra mirror
#
# Env overrides: AGENT (claude-code) MODEL (claude-opus-4-8) N (1) JOB (<task slug>)
#                OUTPUT_DIR (<repo>/output) COPY_TO (unset) BUILD_MULT (3) AT (1)
set -euo pipefail
unset AWS_BEARER_TOKEN_BEDROCK 2>/dev/null || true

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

TASK="${1:?usage: scripts/run_task.sh <task-dir> }"
[ -f "$TASK/task.toml" ] || { echo "not a task dir (no task.toml): $TASK" >&2; exit 2; }
SLUG="$(basename "$TASK")"

AGENT="${AGENT:-claude-code}"
MODEL="${MODEL:-claude-opus-4-8}"
N="${N:-1}"
BUILD_MULT="${BUILD_MULT:-3}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO/output}"
AT="${AT:-1}"
JOB="${JOB:-$SLUG}"   # job dir == output/<task>/ (reshaped in place by the converter)

# --- auth: Harbor's claude-code agent + the LLM judge need a token ----------
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  TOKEN="$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null \
           | python3 -c 'import sys,json; print(json.load(sys.stdin)["claudeAiOauth"]["accessToken"])' 2>/dev/null || true)"
  if [ -n "$TOKEN" ]; then
    export CLAUDE_CODE_OAUTH_TOKEN="$TOKEN"
    echo "[run_task] using Claude Code OAuth token from keychain"
  else
    echo "[run_task] WARNING: no CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY — agent + judge will fail auth" >&2
  fi
fi

# --- docker ------------------------------------------------------------------
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

# --- run (job dir = output/<task>/) ------------------------------------------
RUN_OFFSET=0
if [ -d "$OUTPUT_DIR/$JOB/trajectory" ]; then
  LAST_RUN="$(ls "$OUTPUT_DIR/$JOB/trajectory" 2>/dev/null | grep -E '^Run_[0-9]+$' | sed 's/Run_//' | sort -n | tail -1 || true)"
  [ -n "$LAST_RUN" ] && RUN_OFFSET="$LAST_RUN"
fi
ARGS=(run -y --path "$TASK" --agent "$AGENT" --jobs-dir "$OUTPUT_DIR" --job-name "$JOB" \
      --environment-build-timeout-multiplier "$BUILD_MULT" --n-attempts "$N")
[ "$AGENT" != "oracle" ] && ARGS+=(--model "$MODEL")
echo "[run_task] harbor ${ARGS[*]}"
HARBOR_OUTPUT_OFF=1 command harbor "${ARGS[@]}" || echo "[run_task] harbor exited non-zero; reshaping whatever landed" >&2

# --- reshape in place ---------------------------------------------------------
CONV=(python3 scripts/harbor_to_output.py "$OUTPUT_DIR/$JOB" --output-dir "$OUTPUT_DIR" --at "$AT" --run-offset "$RUN_OFFSET")
[ -n "${COPY_TO:-}" ] && CONV+=(--copy-to "$COPY_TO")
"${CONV[@]}"
echo "[run_task] done → $OUTPUT_DIR/$SLUG"
