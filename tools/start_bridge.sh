#!/usr/bin/env bash
set -euo pipefail

BRIDGE_PORT="${BRIDGE_PORT:-8766}"
CCBRIDGE_PORT="${CCBRIDGE_PORT:-8765}"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    CCPID=$(lsof -ti :"$CCBRIDGE_PORT" 2>/dev/null | head -1)
    if [ -n "$CCPID" ]; then
        ANTHROPIC_API_KEY=$(ps ewwp "$CCPID" 2>/dev/null | tr ' ' '\n' | grep '^WCB_CC_BRIDGE_SECRET=' | head -1 | cut -d= -f2-)
    fi
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ERROR: no ccbridge found on :${CCBRIDGE_PORT} and ANTHROPIC_API_KEY is unset" >&2
    echo "Either start the ccbridge first or set ANTHROPIC_API_KEY=<api-key>" >&2
    exit 1
fi

export ANTHROPIC_API_KEY
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-http://127.0.0.1:${CCBRIDGE_PORT}}"
export BRIDGE_PORT

echo "[claude-bridge] -> ccbridge at ${ANTHROPIC_BASE_URL}"
echo "[claude-bridge] listening on http://127.0.0.1:${BRIDGE_PORT}/v1"
echo ""
echo "    LLM_BASE_URL=http://127.0.0.1:${BRIDGE_PORT}/v1"
echo "    LLM_API_KEY=stub"
echo ""

cd "$(dirname "$0")/.."
exec uv run tools/claude_bridge.py
