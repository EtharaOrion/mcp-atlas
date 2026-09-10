# The shared eval image. ONE image for every task -- built once, referenced by
# tag. Per-task test bodies and the grading code arrive as BIND MOUNTS declared
# in each bundle's tests/docker-compose.yaml, so editing a test or a grader
# never rebuilds anything.
#
#     make build-verifier-base
#
# WHAT IS DELIBERATELY ABSENT
#
# The Claude Code CLI. The agent needs it; the grader does not. Baking it in
# would place an agent runtime inside the container whose whole purpose is to be
# free of one. The rubric judge is pinned to a codex model
# (run_task.sh + patch_harbor.py both set JUDGE_MODEL=gpt-5.6-sol), the
# in-container attempt fails non-fatally as it already does in shared mode, and
# run_task.sh::stage_host_rubric grades the rubric on the host -- measured across
# 44 recorded runs, every single one carries "producer": "host_rubric_pass".
#
# The codex CLI. Using it in-container would mean mounting this machine's
# ChatGPT credential into a task container.
#
# If in-container rubric grading is ever wanted, that is a JUDGE_MODEL decision
# first (point it at a CLAUDE_MODELS entry) and an image decision second. Do not
# bundle it with a container-topology change.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl procps ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

CMD ["sleep", "infinity"]
