FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    fonts-liberation \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Pre-bake the Claude Code CLI. harbor's ClaudeCode.install() would otherwise
# fetch it from downloads.claude.ai INSIDE the container during agent setup,
# which the network-isolation overlay makes unreachable -- the trial then dies
# in setup with an empty /logs/agent. Build time still has an open network, so
# it happens here; scripts/patch_harbor.py no-ops harbor's installer when
# `claude` is already on PATH. procps above is for claude's node-tree-kill,
# which shells out to ps/pgrep.
RUN curl -fsSL https://downloads.claude.ai/claude-code-releases/bootstrap.sh | bash \
    && ln -sf /root/.local/bin/claude /usr/local/bin/claude \
    && claude --version

RUN pip install --no-cache-dir \
    matplotlib \
    pandas \
    Pillow \
    python-docx \
    fpdf2 \
    requests \
    openpyxl "claude-agent-sdk>=0.1.45" pytest "headroom-ai>=0.37,<0.38"

WORKDIR /task

COPY . .

RUN mkdir -p /root/Desktop/veltrix

ENV PYTHONUNBUFFERED=1

CMD ["/bin/bash"]
