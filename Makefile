# Makefile for MCP-Atlas

IMAGE_NAME = agent-environment
VERSION = 1.2.7
GHCR_REPO = ghcr.io/scaleapi/mcp-atlas

.PHONY: build run-docker shell push install-harness run-harness install-python run-eval test build-light-servers judge-codex-check run-eval-codex run-batch batch-status

# ---------------------------------------------------------------------------
# Agent Environment (docker image with the 36 MCP servers)
# ---------------------------------------------------------------------------

run-docker: # run agent-environment container on port 1984
	docker run --rm -p 1984:1984 --env-file .env $(IMAGE_NAME):latest

build: # build agent-environment locally
	cd services/agent-environment && docker buildx build --platform linux/amd64 -t $(IMAGE_NAME) .
	docker tag $(IMAGE_NAME):latest $(IMAGE_NAME):$(VERSION)

shell: # shell into agent-environment
	docker run -it --rm --env-file .env $(IMAGE_NAME):latest bash

# Build and push multi-arch image to ghcr.io
# Requires Docker (may not work with Rancher Desktop)
# First: docker login ghcr.io
push:
	@echo "--- Building and pushing multi-arch $(GHCR_REPO):$(VERSION) and :latest ---"
	cd services/agent-environment && docker buildx build --platform linux/amd64,linux/arm64 \
		-t $(GHCR_REPO):$(VERSION) \
		-t $(GHCR_REPO):latest \
		--push .
	@echo "✓ Successfully pushed to $(GHCR_REPO):$(VERSION)"

# ---------------------------------------------------------------------------
# Agent Harness (TypeScript, talks to agent-environment via MCP_SANDBOX_URL)
# ---------------------------------------------------------------------------

install-harness: # install harness deps
	cd services/agent-harness && npm install

run-harness: # run the TS harness on port 3001 (uses .env in cwd)
	cd services/agent-harness && npm run dev

# ---------------------------------------------------------------------------
# Batch eval runner (top-level run_eval.py)
# ---------------------------------------------------------------------------

install-python: # install all Python deps (run_eval, scoring, diagnostics, test_servers)
	pip install -r requirements.txt

run-eval: # run the full HuggingFace eval (usage: make run-eval MODEL=... OUTPUT=...)
	python run_eval.py --model "$(MODEL)" --output "$(OUTPUT)"

# ---------------------------------------------------------------------------
# Judge backend: Codex subscription via the local codex CLI
# ---------------------------------------------------------------------------
# Both rubric judges (rubric_judge_cli, the one test.sh grades with, and
# score_rubric) shell out to `codex exec` in a read-only sandbox. No bridge
# server, no generated key, no base URL: the only credential is a
# `codex login` this machine already holds, and the whole preflight is one
# CLI call. The model comes from JUDGE_MODEL (default gpt-5.6-sol).

CODEX_JUDGE_MODEL = gpt-5.6-sol

judge-codex-check: # verify the codex CLI is installed and logged in
	codex login status

run-eval-codex: judge-codex-check # run the eval with the judge on the codex CLI
	JUDGE_MODEL=$(CODEX_JUDGE_MODEL) \
	python run_eval.py --model "$(MODEL)" --output "$(OUTPUT)"

# ---------------------------------------------------------------------------
# Tests (run by CI)
# ---------------------------------------------------------------------------
# PYTHON must be >= 3.11: the adapter tests parse generated task.toml with
# tomllib. Older interpreters skip those assertions rather than fail, which
# would quietly stop guarding the Harbor bundle shape.
# Prefer the project venv when it exists: it holds pyyaml/python-dotenv from
# requirements.txt, which a bare system python3 usually does not, and the
# adapter + scoring suites fail at import without them.
PYTEST_PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

test: test-env test-python # run every test suite

test-env: # verify mcp_server_template.json and install_mcp_packages.sh stay in sync
	cd services/agent-environment && uv sync && uv run pytest

test-python: # adapter + scoring + mcp_eval + scripts unit tests (no Docker, no network)
	$(PYTEST_PYTHON) -m pytest adapters services/scoring/tests services/mcp_eval/tests scripts/tests services/light-servers/tests -q

smoke: # end-to-end bundle generation + Harbor validation (no Docker, no network)
	$(PYTEST_PYTHON) scripts/smoke_test.py

# ---------------------------------------------------------------------------
# Harbor task runs → output/<task>/ (complex-mcp "harbor" layout)
# ---------------------------------------------------------------------------
# make run-task TASK=tasks/xenon-atomic-cube [MODEL=claude-opus-5] [AGENT=claude-code] [N=1]
run-task: # run one task via Harbor and emit output/<task>/ (summary, pass_summary, pass@N.json, report.md, trajectory/, .raw/)
	@test -n "$(TASK)" || { echo "usage: make run-task TASK=tasks/<task-dir>"; exit 2; }
	AGENT=$(AGENT) MODEL=$(MODEL) N=$(N) COPY_TO=$(COPY_TO) scripts/run_task.sh $(TASK)

# make run-batch [TASK=tasks/<dir> | ALL=1] [MODEL=...] [N=3] [BATCH=<id>]
run-batch: # run many tasks as one resumable batch; rerun the same command to resume
	@test -n "$(TASK)$(ALL)" || { echo "usage: make run-batch ALL=1 [MODEL=...] [N=...]  |  make run-batch TASK=tasks/<dir>"; exit 2; }
	python3 scripts/run_batch.py $(if $(ALL),--all,--task $(TASK)) \
	  $(if $(MODEL),--model $(MODEL),) $(if $(AGENT),--agent $(AGENT),) \
	  $(if $(N),--n $(N),) $(if $(BATCH),--batch-id $(BATCH),) $(BATCH_ARGS)

# make batch-status [BATCH=<id>]   (defaults to the most recently touched batch)
batch-status: # print a batch's per-step progress without running anything
	python3 scripts/run_batch.py --status $(if $(BATCH),--batch-id $(BATCH),)

# make harbor-output JOB=jobs/<job>
harbor-output: # reshape an existing Harbor job into output/<task>/ without re-running it
	@test -n "$(JOB)" || { echo "usage: make harbor-output JOB=jobs/<job>"; exit 2; }
	python3 scripts/harbor_to_output.py $(JOB) --output-dir output $(if $(COPY_TO),--copy-to $(COPY_TO),)

# make finance-usage RUN=output/<task>/trajectory/Run_1 [DRY=1]
finance-usage: # POST one run's token/cost usage to the Finance API
	@test -n "$(RUN)" || { echo "usage: make finance-usage RUN=output/<task>/trajectory/Run_N [DRY=1]"; exit 2; }
	python3 scripts/finance_reporter.py --run-dir $(RUN) $(if $(DRY),--dry-run,)

build-light-servers: # build light-servers Docker image (all software + utility servers bundled in services/light-servers/)
	docker build -t light-servers:latest services/light-servers/
