.PHONY: help install dev serve tunnel test lint fmt setup deploy

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install:  ## Sync the virtualenv from the lockfile
	uv sync

dev:  ## ADK dev UI (anonymous mode — no Workspace tools)
	uv run adk web agents

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
	./deploy/deploy_cloud_run.sh
