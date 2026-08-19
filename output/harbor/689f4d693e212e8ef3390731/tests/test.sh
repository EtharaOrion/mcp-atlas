#!/bin/bash
# Forward LLM auth env vars from the host (default to empty if unset).
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-}"
export LITELLM_API_KEY="${LITELLM_API_KEY:-}"
export LITELLM_BASE_URL="${LITELLM_BASE_URL:-}"
uv run /tests/agent_judge.py
