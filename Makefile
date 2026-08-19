# Makefile for MCP-Atlas

IMAGE_NAME = agent-environment
VERSION = 1.2.7
GHCR_REPO = ghcr.io/scaleapi/mcp-atlas

.PHONY: build run-docker shell push install-harness run-harness install-python run-eval test

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
# Tests (run by CI)
# ---------------------------------------------------------------------------
# PYTHON must be >= 3.11: the adapter tests parse generated task.toml with
# tomllib. Older interpreters skip those assertions rather than fail, which
# would quietly stop guarding the Harbor bundle shape.
PYTEST_PYTHON ?= python3

test: test-env test-python # run every test suite

test-env: # verify mcp_server_template.json and install_mcp_packages.sh stay in sync
	cd services/agent-environment && uv sync && uv run pytest

test-python: # adapter + scoring + mcp_eval unit tests (no Docker, no network)
	$(PYTEST_PYTHON) -m pytest adapters services/scoring/tests services/mcp_eval/tests -q

smoke: # end-to-end bundle generation + Harbor validation (no Docker, no network)
	$(PYTEST_PYTHON) scripts/smoke_test.py
