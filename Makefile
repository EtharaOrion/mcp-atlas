# Makefile for MCP-Atlas

IMAGE_NAME = agent-environment
VERSION = 1.2.7
GHCR_REPO = ghcr.io/scaleapi/mcp-atlas

.PHONY: build run-docker shell push install-harness run-harness install-python run-eval test build-light-servers grade-env grade-build grade-wait grade-down check-isolation judge-codex-check run-eval-codex run-batch batch-status

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
	python3 tools/delivery/harbor_to_output.py $(JOB) --output-dir output $(if $(COPY_TO),--copy-to $(COPY_TO),)

# make finance-usage RUN=output/<task>/trajectory/Run_1 [DRY=1]
finance-usage: # POST one run's token/cost usage to the Finance API
	@test -n "$(RUN)" || { echo "usage: make finance-usage RUN=output/<task>/trajectory/Run_N [DRY=1]"; exit 2; }
	python3 tools/finance/finance_reporter.py --run-dir $(RUN) $(if $(DRY),--dry-run,)

build-light-servers: # build light-servers Docker image (all software + utility servers bundled in services/light-servers/)
	docker build -t light-servers:latest services/light-servers/

# NOTE: `build-verifier-base` is gone. Each bundle's tests/Dockerfile now starts
# FROM python:3.12-slim and installs the shared grader deps itself, because the
# build context Harbor pins for a verifier env is tests/ and cannot reach a file
# at the repo root. Each bundle bakes its own pins inline and
# list and test_grader_compress_wiring.py asserts the bundles match it.

# NOTE: `build-rubric-judge` is gone, along with services/rubric-judge/. Every
# bundle now defines its own judge image inline in its compose file, so there is
# no shared image to build. A bundle that still expects one has not been
# migrated; host_rubric_pass.py refuses rather than grading it without a rubric.

build-egress-proxy: # build the egress allowlist proxy (network isolation for the agent phase)
	docker build -t egress-proxy:latest tools/network/egress-proxy/

# ---------------------------------------------------------------------------
# Compose-orchestrated grading (plan.md)
#
# OPT-IN. The `verifier` and `rubric` services carry profiles: ["grading"], so
# nothing below runs unless COMPOSE_PROFILES=grading is set. A plain harbor run
# against the same bundle is unaffected -- that is the point of the profile, and
# it stays that way until parity is proven at a fixed seed against the
# shared-mode baseline.
# ---------------------------------------------------------------------------

TASK ?= tasks/homes-tour-packet-visuals

# HOW THE AGENT PHASE ACTUALLY HAPPENS.
#
# These services do not run the agent -- `main` is `sleep infinity` and harbor
# is still what execs the agent into it and fires the collect hook that releases
# the graders. The integration needs NO harbor patch, just three things set on
# the harbor invocation:
#
#   COMPOSE_PROFILES=grading   harbor shells out to `docker compose`, which
#                              reads this from the environment, so the two
#                              grading services come up in harbor's OWN project
#                              alongside main and light-servers.
#   --disable-verification     harbor must NOT also run its own verifier. Left
#                              on, the bundle is graded twice and the second
#                              grader BILLS THE JUDGE AGAIN (its test.sh runs
#                              stage 3 with no ATLAS_RUBRIC_SIBLING set).
#   --no-delete                harbor tears the project down as soon as its own
#                              verifier phase returns, which with verification
#                              disabled is immediately. Without this it kills
#                              both graders mid-flight, seconds after the
#                              sentinel released them.
#
# Then `make grade-wait` blocks until the graders finish and tears down.
grade-env: # print the harbor invocation this profile requires
	@echo 'COMPOSE_PROFILES=grading <your harbor/run_task invocation> \'
	@echo '  --disable-verification --no-delete'
	@echo ''
	@echo 'then: make grade-wait TASK=$(TASK)'

grade-build: # build the two grading images for TASK
	COMPOSE_PROFILES=grading docker compose \
	  -f "$(TASK)/environment/docker-compose.yaml" build verifier rubric

# Blocks on the VERIFIER, not on the rubric: the verifier is last to finish by
# construction (it waits for the rubric's verdict before running pytest, because
# test_outputs.py folds the rubric into the weighted ledger at pytest time).
# Waiting on the rubric instead would tear down while pytest was still running.
grade-wait: # after a --no-delete harbor run: wait for grading, report, tear down
	@COMPOSE_PROFILES=grading ATLAS_VOL="$${ATLAS_VOL:-atlas}" docker compose \
	  -f "$(TASK)/environment/docker-compose.yaml" -p "$${ATLAS_PROJ:-atlasgrade}" wait verifier \
	  && echo "[grade] verifier finished" || echo "[grade] verifier exited non-zero"
	@echo "── reward ──"; docker run --rm \
	  -v "$${ATLAS_VOL:-atlas}_grade_out:/s:ro" alpine:3.21 cat /s/reward.json 2>/dev/null \
	  || echo "NO reward.json -- check: docker run --rm -v $${ATLAS_VOL:-atlas}_grade_out:/s alpine ls /s"
	@echo "── rubric ──"; docker run --rm \
	  -v "$${ATLAS_VOL:-atlas}_judge_out:/s:ro" alpine:3.21 \
	  sh -c 'test -s /s/rubric_breakdown.json && echo graded || { echo "UNSCORED:"; cat /s/judge_error.txt 2>/dev/null; }' 2>/dev/null \
	  || echo "(judge output volume empty)"
	COMPOSE_PROFILES=grading ATLAS_VOL="$${ATLAS_VOL:-atlas}" docker compose \
	  -f "$(TASK)/environment/docker-compose.yaml" -p "$${ATLAS_PROJ:-atlasgrade}" down -v

grade-down: # tear down the grading project without waiting (aborts grading)
	COMPOSE_PROFILES=grading docker compose \
	  -f "$(TASK)/environment/docker-compose.yaml" down -v

# Proves the isolation contract instead of asserting it. Run DURING the agent
# phase, while every container is up -- that is the only window in which a leak
# is reachable. Cheap enough to run every time, and it is what catches the day
# somebody adds a convenience mount to `main`.
#
# Exits non-zero on the FIRST leak found. Each probe is a separate line so the
# failure names the specific thing that leaked rather than just "isolation bad".
check-isolation: # assert the agent cannot see the tests, the rubric or the graders
	@docker compose -f "$(TASK)/environment/docker-compose.yaml" exec -T main sh -c '\
	  ls /tests               >/dev/null 2>&1 && { echo "LEAK: /tests visible to the agent";       exit 1; }; \
	  ls /judge-in            >/dev/null 2>&1 && { echo "LEAK: /judge-in writable by the agent";   exit 1; }; \
	  ls /var/run/docker.sock >/dev/null 2>&1 && { echo "LEAK: docker.sock -- agent can read the verifier image"; exit 1; }; \
	  getent hosts verifier   >/dev/null 2>&1 && { echo "LEAK: verifier reachable over the network"; exit 1; }; \
	  getent hosts rubric     >/dev/null 2>&1 && { echo "LEAK: rubric reachable over the network";   exit 1; }; \
	  find / -name oracle.json -o -name rubric.json -o -name test_outputs.py 2>/dev/null \
	    | grep . && { echo "LEAK: answer key on disk in the agent container"; exit 1; }; \
	  echo "isolation OK"'

# ---------------------------------------------------------------------------
# zbridge — GLM-5.3 via z.ai (Anthropic-to-GLM proxy + OpenAI adapter)
# Requires ZB_ZAI_API_KEY and ZB_BRIDGE_SECRET in .env
# ---------------------------------------------------------------------------
.PHONY: run-zbridge run-zbridge-adapter eval-glm

run-zbridge: # start zbridge proxy on port 8766 (Anthropic→GLM translator)
	bash tools/bridges/start_zbridge.sh

run-zbridge-adapter: # start zbridge OpenAI-compat adapter on port 4001
	@test -f .env && set -a && source .env && set +a; \
	cd tools/bridges/zbridge-adapter && \
	ZBRIDGE_URL=$${ZBRIDGE_URL:-http://127.0.0.1:8766} \
	ZB_BRIDGE_SECRET=$${ZB_BRIDGE_SECRET} \
	ZBRIDGE_ADAPTER_PORT=$${ZBRIDGE_ADAPTER_PORT:-4001} \
	python zbridge_adapter.py

eval-glm: # run eval through zbridge adapter (usage: make eval-glm MODEL=claude-sonnet-4-6 OUTPUT=output/glm.csv)
	LLM_BASE_URL=$${LLM_BASE_URL:-http://localhost:4001} \
	python run_eval.py --model "$(MODEL)" --output "$(OUTPUT)"

# ---------------------------------------------------------------------------
# Harness teardown
# ---------------------------------------------------------------------------
.PHONY: stop-harness

# make stop-harness [DRY=1] [ALL=1] [FORCE=1]
#   DRY=1    show what would go, change nothing
#   ALL=1    prune every stopped container / unused volume on the machine,
#            not just the harness-scoped ones
#   FORCE=1  tear down even while a run is live (kills it mid-trial)
stop-harness: # kill the background bridges and reap stopped containers + unused volumes (images and build cache kept)
	bash scripts/stop_harness.sh $(if $(DRY),--dry-run,) $(if $(ALL),--all,) $(if $(FORCE),--force,)
