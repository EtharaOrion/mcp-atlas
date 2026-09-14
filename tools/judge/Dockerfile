# The judge container: codexbridge + the codex CLI + the shared rubric grader.
#
# The grader is baked in rather than mounted, so the running container holds no
# host directory at all -- only the one read-only codex login compose mounts.
# That needs the scoring tree as a named build context:
#
#   docker build --build-context scoring=services/scoring -t codex-judge:latest tools/judge
#
# scripts/run_task.sh (ensure_image) and `make build-codex-judge` both pass it.
# A plain `docker build tools/judge` fails on the COPY --from=scoring line.
FROM node:22-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5

RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Same CLI version the host grades with, so a container grade and a host
# fallback grade come from the same judge.
ARG CODEX_VERSION=0.154.0
RUN npm install -g "@openai/codex@${CODEX_VERSION}" && npm cache clean --force \
    && codex --version

COPY --from=scoring rubric_judge_cli.py grader_compress.py /judge/
COPY codexbridge.py /judge/

USER node
ENV CODEX_HOME=/home/node/.codex \
    JUDGE_PORT=8770 \
    JUDGE_MODEL=gpt-5.6-sol \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8770
ENTRYPOINT ["python3", "/judge/codexbridge.py"]
