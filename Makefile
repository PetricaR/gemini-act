.PHONY: help install install-obscura local dev voice mcp mcp-http mcp-tools serve tunnel test lint fmt setup deploy deploy-adk-ui

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install:  ## Sync the virtualenv from the lockfile
	uv sync

install-obscura:  ## Install the Obscura headless browser binary
	./scripts/install_obscura.sh

local:  ## Run the full app locally (FastAPI backend + React Web UI)
	./start_local.sh

dev:  ## ADK dev UI (anonymous mode — no Workspace tools)
	uv run adk web src/adk_apps

voice:  ## Talk to the agent out loud (ADK dev UI, pick `live_agent`, click the mic)
	@echo "Open http://localhost:8000, select the \033[1mlive_agent\033[0m agent, then click the microphone."
	uv run adk web src/adk_apps

mcp:  ## Run the imobiliare MCP server on stdio (what a desktop client launches)
	uv run imobiliare-mcp

mcp-http:  ## Run the imobiliare MCP server over streamable HTTP on :8081
	uv run imobiliare-mcp --transport streamable-http --port 8081

mcp-tools:  ## Print the imobiliare MCP tool catalogue (no server, no config needed)
	uv run imobiliare-mcp --list-tools

serve:  ## Run the Chat webhook locally on :8080
	uv run uvicorn gemini_act.chat.app:app --reload --port 8080

tunnel:  ## Expose :8080 publicly so Google Chat can reach it
	cloudflared tunnel --url http://localhost:8080

test:  ## Run the test suite
	uv run pytest -q

lint:  ## Lint
	uv run ruff check .

fmt:  ## Format
	uv run ruff format . && uv run ruff check --fix .

setup:  ## One-time Google Cloud setup
	./deploy/setup_gcp.sh

deploy:  ## Build and deploy to Cloud Run
	./deploy/deploy.sh

deploy-imobiliare:  ## Deploy the valuation service (React report API + MCP endpoint)
	./deploy/deploy_imobiliare.sh

deploy-adk-ui:  ## Deploy the ADK dev web UI to Cloud Run (IAP-locked)
	./deploy/adk_ui/deploy_cloud_run.sh
