#!/usr/bin/env bash
# Is the Bedrock credential + model usable, before spending an agent phase on it?
#
#   scripts/bedrock_probe.sh                 # reads AWS_BEARER_TOKEN_BEDROCK, AWS_REGION,
#                                            # BEDROCK_MODEL_ID from the environment, else .env
#   scripts/bedrock_probe.sh --invoke        # also make ONE 1-token model call (fraction of a cent)
#
# Three requests, cheapest first, each printed as HTTP status + body head. The
# token is never printed.
#
#   1. GET  bedrock.<region>/foundation-models         control plane, free.
#        200 -> the key is valid and may call the control plane
#        403 -> the key is rejected OR lacks control-plane permission
#   2. GET  bedrock.<region>/inference-profiles/<ARN>  control plane, free.
#        This is the call Claude Code makes first to resolve an
#        application-inference-profile ARN (bedrock:GetInferenceProfile).
#   3. POST bedrock-runtime.<region>/model/<ARN>/converse   (--invoke only)
#        maxTokens=1. 200 here means the key can invoke the profile: the run
#        will work once the control plane is either permitted or tolerated.
#
# Reading the verdicts:
#   1=200 2=200 3=200   everything works; a failing run is a harness problem
#   1=200 2=403         key valid, but no GetInferenceProfile on this profile
#   1=403 2=403         key rejected outright (expired, revoked, wrong account)
#   3=400 "on-demand"   profile/model not invocable on demand in this region
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# Fill-if-unset from .env, same rule as run_task.sh: the environment wins.
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line; do
    key="${line%%=*}"; val="${line#*=}"
    case "$key" in AWS_BEARER_TOKEN_BEDROCK|AWS_REGION|BEDROCK_MODEL_ID) ;; *) continue ;; esac
    [ -z "${!key+set}" ] && export "$key=$val"
  done < <(sed 's/[[:space:]]*$//' "$REPO/.env" | grep -E '^[A-Za-z_][A-Za-z0-9_]*=')
fi

TOK="${AWS_BEARER_TOKEN_BEDROCK:-}"
REGION="${AWS_REGION:-}"
MODEL="${BEDROCK_MODEL_ID:-${MODEL:-}}"
[ -n "$TOK" ]    || { echo "AWS_BEARER_TOKEN_BEDROCK is not set (environment or .env)" >&2; exit 2; }
[ -n "$REGION" ] || { echo "AWS_REGION is not set" >&2; exit 2; }
[ -n "$MODEL" ]  || { echo "BEDROCK_MODEL_ID is not set" >&2; exit 2; }
echo "region: $REGION"
echo "model:  $MODEL"
echo "token:  ${#TOK} chars, starts ${TOK:0:4}"

ENC="$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=""))' "$MODEL")"

probe() {  # probe <label> <curl args...>
  local label="$1"; shift
  local body code
  body="$(curl -sS -m 60 -w '\n__HTTP_%{http_code}__' -H "Authorization: Bearer $TOK" "$@" 2>&1 || true)"
  code="$(printf '%s' "$body" | grep -oE '__HTTP_[0-9]+__' | tail -1 | tr -dc '0-9')"
  body="$(printf '%s' "$body" | sed 's/__HTTP_[0-9]*__//')"
  echo
  echo "== $label"
  echo "HTTP ${code:-none}"
  printf '%s\n' "$body" | head -c 700; echo
}

probe "1. control plane: ListFoundationModels (free)" \
  "https://bedrock.$REGION.amazonaws.com/foundation-models?byProvider=anthropic"

probe "2. control plane: GetInferenceProfile (free; what Claude Code calls first)" \
  "https://bedrock.$REGION.amazonaws.com/inference-profiles/$ENC"

if [ "${1:-}" = "--invoke" ]; then
  probe "3. runtime: Converse maxTokens=1 (one tiny paid call)" \
    -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":[{"text":"hi"}]}],"inferenceConfig":{"maxTokens":1}}' \
    "https://bedrock-runtime.$REGION.amazonaws.com/model/$ENC/converse"
else
  echo
  echo "(skipped 3: rerun with --invoke to make one 1-token model call)"
fi
