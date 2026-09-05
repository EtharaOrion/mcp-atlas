# Makefile for MCP-Atlas

IMAGE_NAME = agent-environment
VERSION = 1.2.7
GHCR_REPO = ghcr.io/scaleapi/mcp-atlas

.PHONY: build run-docker shell push install-harness run-harness install-python run-eval test build-light-servers judge-bridge judge-bridge-check judge-config judge-smoke judge-smoke-live run-eval-codex run-batch batch-status

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
# Judge backend: Codex subscription via codex-bridge
# ---------------------------------------------------------------------------
# services/scoring/rubric_judge.py resolves its endpoint from EVAL_LLM_BASE_URL
# and its model from JUDGE_MODEL, so this is configuration rather than a code
# change. The one thing that is not configuration is the provider path:
# codex-bridge serves Anthropic Messages and OpenAI Responses and has no
# chat/completions, so the Codex models route through litellm's `anthropic/`
# provider. codex_bridge.provider_route owns that.
#
# The bridge is CodingForMoney/codex-bridge. It binds 127.0.0.1:3456, requires
# an API key on every route except /health, and fulfils requests from
# ~/.codex/auth.json -- so Codex must already be signed in. It has no login
# subcommand and never writes auth.json.

CODEX_BRIDGE_ROOT = http://127.0.0.1:3456
# litellm's anthropic provider appends /v1/messages, so the judge gets the root
# with no /v1. From inside the task container the host is host.docker.internal,
# not 127.0.0.1, which is the difference that makes a host-side preflight pass
# and every in-container call still fail.
CODEX_BRIDGE_ROOT_CONTAINER = http://host.docker.internal:3456
CODEX_JUDGE_MODEL = gpt-5.6-sol

judge-bridge: # run codex-bridge in the foreground (ctrl-c to stop)
	codex-bridge serve

# Writes ~/.cb/judge_backend.json -- HOST-SIDE, and deliberately NOT
# services/scoring/judge_backend.json, which is where it used to go.
#
# That directory is bind-mounted read-only at /harness/scoring, and every
# bundle's task.toml sets [verifier] environment_mode = "shared", so the
# verifier runs in the same container as the graded agent. A key written there
# is readable by the agent for the whole run. It bought nothing: the only
# grader tests/test.sh invokes is rubric_judge_cli.py, which does not import
# codex_bridge and takes its credential from [verifier.env]. The digest that
# supposedly forbade the alternative does not cover the shipped bundle either
# -- .memory/crucible_view.yaml task_artifact_hashes has no Amandeep entry.
#
# The URL is still the container's view of the host, not 127.0.0.1, for the
# host-side smoke path that does read this file.
judge-config: # write the judge backend config, host-side and unmounted
	@python3 -c "import json,os,sys; sys.path.insert(0,'services/scoring'); \
	import codex_bridge as c; \
	p=c.JUDGE_BACKEND_CONFIG; \
	p.parent.mkdir(mode=0o700, parents=True, exist_ok=True); \
	p.write_text(json.dumps({'EVAL_LLM_BASE_URL':'$(CODEX_BRIDGE_ROOT_CONTAINER)', \
	'EVAL_LLM_API_KEY':c.api_key() or '', 'JUDGE_MODEL':'$(CODEX_JUDGE_MODEL)'}, indent=2)+chr(10)); \
	os.chmod(p, 0o600); \
	print('wrote', p)"
	@python3 -c "import sys; sys.path.insert(0,'services/scoring'); \
	import codex_bridge as c; s=c.mounted_secret_leak(); \
	sys.exit(0) if s is None else (print('REFUSING: %s is inside the /harness/scoring mount the graded agent can read. Delete it.' % s, file=sys.stderr), sys.exit(1))"

judge-smoke: # end-to-end judge smoke test against an in-process stub (no bridge, free)
	python3 scripts/judge_smoke_test.py

judge-smoke-live: judge-bridge-check # same, against a real bridge (spends plan calls)
	python3 scripts/judge_smoke_test.py --live

judge-bridge-check: # verify the bridge is up, authenticated, and serves the model
	python3 -c "import sys; sys.path.insert(0,'services/scoring'); \
	import codex_bridge as c; print(c.preflight(model='$(CODEX_JUDGE_MODEL)').detail)"

# The key is generated by the bridge and stored at ~/.cb/config.json;
# codex_bridge.api_key() reads it, so it need not be exported by hand.
run-eval-codex: judge-bridge-check judge-config # run the eval with the judge on codex-bridge
	EVAL_LLM_BASE_URL=$(CODEX_BRIDGE_ROOT_CONTAINER) \
	EVAL_LLM_API_KEY=$$(python3 -c "import sys; sys.path.insert(0,'services/scoring'); \
	import codex_bridge as c; print(c.api_key() or '')") \
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
	$(PYTEST_PYTHON) -m pytest adapters services/scoring/tests services/mcp_eval/tests scripts/tests services/light-servers/tests audit/tests -q

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

# ---------------------------------------------------------------------------
# zbridge — GLM-5.3 via z.ai (Anthropic-to-GLM proxy + OpenAI adapter)
# Requires ZB_ZAI_API_KEY and ZB_BRIDGE_SECRET in .env
# ---------------------------------------------------------------------------
.PHONY: run-zbridge run-zbridge-adapter eval-glm

run-zbridge: # start zbridge proxy on port 8766 (Anthropic→GLM translator)
	bash scripts/start_zbridge.sh

run-zbridge-adapter: # start zbridge OpenAI-compat adapter on port 4001
	@test -f .env && set -a && source .env && set +a; \
	cd services/zbridge-adapter && \
	ZBRIDGE_URL=$${ZBRIDGE_URL:-http://127.0.0.1:8766} \
	ZB_BRIDGE_SECRET=$${ZB_BRIDGE_SECRET} \
	ZBRIDGE_ADAPTER_PORT=$${ZBRIDGE_ADAPTER_PORT:-4001} \
	python zbridge_adapter.py

eval-glm: # run eval through zbridge adapter (usage: make eval-glm MODEL=claude-sonnet-4-6 OUTPUT=output/glm.csv)
	LLM_BASE_URL=$${LLM_BASE_URL:-http://localhost:4001} \
	python run_eval.py --model "$(MODEL)" --output "$(OUTPUT)"
