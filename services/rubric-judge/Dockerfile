# The RUBRIC JUDGE container.
#
# BUILD CONTEXT IS services/, NOT services/rubric-judge/ -- that is what lets
# `COPY scoring/` reach the judge source. Build with:
#   make build-rubric-judge
#
# WHY THIS IS A THIRD IMAGE AND NOT PART OF verifier-base
# -------------------------------------------------------
# The other two channels grade by reading files: pytest checks deliverables,
# state_dump compares world snapshots. Both are deterministic and need no
# credential. The rubric channel is an LLM call, and the judge it calls needs
# an operator credential.
#
# Giving it its own image means that credential is mounted into a container
# holding NOTHING but the judge: no agent runtime, no /workspace, no answer
# key, no test_outputs.py, no oracle.json.
#
# The verifier container holds all of those. Its eval image bakes the bundle's
# whole tests/ tree at /tests (tests/Dockerfile: COPY . /tests/) and its compose
# override binds the shared grader at /harness/scoring, so by the time it runs
# it has the answer key, the oracle and every assertion in one place. Putting
# the judge there would hand the credential that entire blast radius for no
# gain -- the judge reads a rubric and a trajectory and nothing else.
#
# rubric_judge_cli.py:181 refuses to mount the operator's ChatGPT credential
# into "a container that just ran an untrusted agent". That objection is about
# the AGENT container, which in shared mode was the only container going. It
# does not apply here: this image never runs an agent, never sees agent code,
# and is handed two JSON files in exchange for two JSON files.
FROM python:3.12-slim

# nodejs/npm exist ONLY to carry the codex CLI. Nothing in this image runs JS
# directly and no JS is copied in.
RUN apt-get update && apt-get install -y --no-install-recommends \
      nodejs npm ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# PINNED to the CLI version on the host that produced the existing baselines
# (`codex --version` -> codex-cli 0.153.4). A judge verdict is a function of
# model AND harness, so an unpinned `npm install -g @openai/codex` would move
# every reward silently the next time this image happened to be rebuilt.
RUN npm install -g @openai/codex@0.153.4 \
    && codex --version

# grader_compress.py imports headroom when GRADER_HEADROOM_ENABLED=true, and
# compression rewrites the PROMPT the judge reads. This pin exists for scoring
# parity with the host .venv (headroom 0.37.0), not for convenience.
RUN pip install --no-cache-dir "headroom-ai>=0.37,<0.38"

# Two files, not the whole scoring tree -- see the blast-radius note above.
# rubric_judge_cli.py falls back to inserting its own directory on sys.path
# (rubric_judge_cli.py:42-44), so grader_compress.py only has to sit beside it.
COPY scoring/rubric_judge_cli.py /harness/scoring/rubric_judge_cli.py
COPY scoring/grader_compress.py  /harness/scoring/grader_compress.py

# A MINIMAL codex config, baked. The host's ~/.codex/config.toml is
# deliberately NOT mounted: it registers an MCP server at a host path that does
# not exist in here (codex would try to spawn it on every judge call) and it
# carries the operator's entire trusted-project list, which has no business in
# a grading container. /tmp is the trusted project because _codex_exec runs the
# CLI with cwd=tempfile.gettempdir() (rubric_judge_cli.py:348).
COPY rubric-judge/config.toml /opt/rubric-judge/config.toml

# Runs as the CALLING uid (`docker run --user`) so the two output files land on
# the host owned by the operator rather than by root. That means HOME has to be
# writable by a uid this image has never heard of -- codex rewrites auth.json
# when it refreshes its OAuth token and dies if it cannot.
ENV HOME=/tmp/judge-home \
    CODEX_HOME=/tmp/judge-home/.codex \
    PYTHONDONTWRITEBYTECODE=1
RUN mkdir -p /tmp/judge-home/.codex && chmod -R 777 /tmp/judge-home

COPY rubric-judge/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
