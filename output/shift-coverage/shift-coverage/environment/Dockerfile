FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Pre-resolve the bridge's inline dependencies at build time so the agent
# does not pay a package download on its first tool call (and so the task
# still starts on a network-restricted runner).
COPY mcp_rest_bridge.py /opt/mcp-bridge/mcp_rest_bridge.py
COPY enabled_tools.txt /enabled_tools.txt
RUN uv run --no-project /opt/mcp-bridge/mcp_rest_bridge.py --help >/dev/null 2>&1 || true
