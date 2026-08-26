FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends npm bash git procps curl gettext-base && rm -rf /var/lib/apt/lists/*

# Need to install nodejs from elsewhere, because bookworm-slim is based on debian, and the available version of nodejs is 18, which is too old
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Pre-install all MCP server packages (NPX and UVX), saves approx 1 minute of startup time
COPY dev_scripts/install_mcp_packages.sh /
RUN /install_mcp_packages.sh && rm /install_mcp_packages.sh

# Copy project files and set up workspace
WORKDIR /agent-environment
COPY . .
RUN uv venv --python 3.12

# Move /agent-environment/data to /data
RUN mkdir -p /data
RUN mv /agent-environment/data/* /data/ 2>/dev/null || true
RUN rm -rf /agent-environment/data

# Install git submodules from CSV to specified directories
RUN while IFS=',' read -r url sha path; do \
    echo "Installing $url at $sha to $path"; \
    rm -rf "$path" 2>/dev/null || true; \
    git clone "$url" "$path"; \
    cd "$path" && git checkout "$sha"; \
done < /data/repos/git_submodule_info.csv

# Set up MCP code executor workspace (depends on copied repo structure)
WORKDIR /data/repos/mcp_code_executor_workspace
RUN uv sync
WORKDIR /agent-environment

RUN rm -rf /agent-environment/dev_scripts

# Sync project dependencies (requires pyproject.toml and uv.lock from COPY)
RUN uv sync

# Run as a non-root user. Everything above this line is build-time and stays
# root, so the apt, npm, uvx and uv sync steps are unaffected. The uid matches
# the one light-servers and the bundle images use, so a shared workspace volume
# stays writable across all of them.
#
# Three paths have to be writable at runtime rather than only at build time:
# /agent-environment because entrypoint.sh renders mcp_server_config.json into
# src/ and uv resolves .venv there, /data because the code-executor workspace
# is used as a scratch area, and HOME because the npx- and uvx-spawned MCP
# servers write their own caches.
RUN useradd --system --create-home --uid 10001 app \
    && chown -R app:app /agent-environment /data
ENV HOME=/home/app \
    UV_CACHE_DIR=/home/app/.cache/uv \
    XDG_CACHE_HOME=/home/app/.cache \
    NPM_CONFIG_CACHE=/home/app/.npm
USER app

EXPOSE 1984

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:1984/health || exit 1

# Set the entrypoint (this always runs to generate mcp_server_config.json from template)
ENTRYPOINT ["/agent-environment/entrypoint.sh"]

# Set the default command (users can override this)
CMD ["uv", "run", "python", "-m", "uvicorn", "agent_environment.main:app", "--host", "0.0.0.0", "--port", "1984"]
