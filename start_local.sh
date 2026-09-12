#!/usr/bin/env bash
# ==============================================================================
# Evaluator AI & Gemini Act - Local Startup Script
# ==============================================================================
# Starts both the FastAPI Backend (port 8080) and React Web UI (port 3000).
# Features:
#   - Automatic project directory detection
#   - Environment variable loading (.env)
#   - Automatic dependency installation if missing (uv/python, npm)
#   - Pre-flight port checking and release
#   - Frontend compilation & live dev server
#   - Graceful shutdown trapping (Ctrl+C kills all background processes)
# ==============================================================================

set -eo pipefail

# ANSI Color codes for clean output
CLR_RESET="\033[0m"
CLR_BOLD="\033[1m"
CLR_CYAN="\033[1;36m"
CLR_GREEN="\033[1;32m"
CLR_YELLOW="\033[1;33m"
CLR_RED="\033[1;31m"
CLR_DIM="\033[2m"

# Locate base directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
  BASE_DIR="$SCRIPT_DIR"
elif [[ -f "$SCRIPT_DIR/gemini-act/pyproject.toml" ]]; then
  BASE_DIR="$SCRIPT_DIR/gemini-act"
else
  echo -e "${CLR_RED}Error: Cannot locate gemini-act directory containing pyproject.toml.${CLR_RESET}"
  exit 1
fi

WEB_DIR="$BASE_DIR/web"
BACKEND_PORT=8080
FRONTEND_PORT=3000

echo -e "${CLR_CYAN}${CLR_BOLD}==============================================================================${CLR_RESET}"
echo -e "${CLR_CYAN}${CLR_BOLD}  🏢 Evaluator AI & Gemini Act — Local Environment Launcher${CLR_RESET}"
echo -e "${CLR_CYAN}${CLR_BOLD}==============================================================================${CLR_RESET}"
echo -e "${CLR_DIM}Project directory: $BASE_DIR${CLR_RESET}"

# 1. Load .env if present
if [[ -f "$BASE_DIR/.env" ]]; then
  echo -e "${CLR_GREEN}✔${CLR_RESET} Loading environment from $BASE_DIR/.env"
  set -a
  # shellcheck source=/dev/null
  source "$BASE_DIR/.env"
  set +a
elif [[ -f "$SCRIPT_DIR/.env" ]]; then
  echo -e "${CLR_GREEN}✔${CLR_RESET} Loading environment from $SCRIPT_DIR/.env"
  set -a
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/.env"
  set +a
else
  echo -e "${CLR_YELLOW}ℹ${CLR_RESET} No .env file found. Running with default local settings (Demo mode active)."
fi

# Ensure reports directory exists
mkdir -p "$BASE_DIR/reports"

# 2. Check and clean up ports 8080 and 3000 if occupied
release_port() {
  local port=$1
  local pids
  pids=$(lsof -ti :"$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo -e "${CLR_YELLOW}⚠${CLR_RESET} Port $port is in use by PID(s): $pids. Releasing..."
    kill -9 $pids 2>/dev/null || true
    sleep 0.5
  fi
}

release_port "$BACKEND_PORT"
release_port "$FRONTEND_PORT"

# 3. Verify Python & Virtual Environment
cd "$BASE_DIR"

PYTHON_BIN=""
UVICORN_BIN=""

if [[ -f "$BASE_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$BASE_DIR/.venv/bin/python"
  UVICORN_BIN="$BASE_DIR/.venv/bin/uvicorn"
elif command -v uv >/dev/null 2>&1; then
  echo -e "${CLR_YELLOW}ℹ${CLR_RESET} Syncing Python environment with uv..."
  uv sync
  PYTHON_BIN="$BASE_DIR/.venv/bin/python"
  UVICORN_BIN="$BASE_DIR/.venv/bin/uvicorn"
else
  echo -e "${CLR_RED}Error: Neither $BASE_DIR/.venv nor 'uv' package manager was found.${CLR_RESET}"
  echo "Please install uv (curl -LsSf https://astral.sh/uv/install.sh | sh) or create a virtualenv at $BASE_DIR/.venv."
  exit 1
fi

# 4. Verify Node.js, npm, and Web UI dependencies
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo -e "${CLR_RED}Error: Node.js and npm are required to run the Web UI.${CLR_RESET}"
  echo "Please install Node.js from https://nodejs.org or via Homebrew ('brew install node')."
  exit 1
fi

if [[ ! -d "$WEB_DIR/node_modules" ]]; then
  echo -e "${CLR_YELLOW}ℹ${CLR_RESET} Installing frontend dependencies in $WEB_DIR..."
  (cd "$WEB_DIR" && npm install)
fi

# Build static dist once so FastAPI direct UI is always updated
if [[ ! -d "$WEB_DIR/dist" || "$1" == "--build" ]]; then
  echo -e "${CLR_YELLOW}ℹ${CLR_RESET} Compiling React production bundle..."
  (cd "$WEB_DIR" && npm run build)
fi

# Check for mode flags
PROD_ONLY=false
if [[ "$1" == "--prod" || "$1" == "--backend-only" ]]; then
  PROD_ONLY=true
fi

# Track background process IDs
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo -e "${CLR_YELLOW}Shutting down services cleanly...${CLR_RESET}"
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  # Allow child processes a moment to terminate
  sleep 0.5
  echo -e "${CLR_GREEN}✔ All services stopped.${CLR_RESET}"
  exit 0
}

# Trap termination signals
trap cleanup SIGINT SIGTERM

# 5. Start Backend (FastAPI on port 8080)
echo -e "${CLR_GREEN}▶${CLR_RESET} Starting FastAPI backend on http://0.0.0.0:$BACKEND_PORT..."
cd "$BASE_DIR"
"$UVICORN_BIN" gemini_act.chat.app:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!

# Wait for backend to be responsive
echo -n "Waiting for backend to be ready..."
for i in {1..12}; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo -e " ${CLR_RED}FAILED${CLR_RESET}"
    echo "Backend process exited unexpectedly. Check logs above."
    exit 1
  fi
  if curl -s -f "http://127.0.0.1:$BACKEND_PORT/healthz" >/dev/null 2>&1; then
    echo -e " ${CLR_GREEN}READY${CLR_RESET}"
    break
  fi
  sleep 0.5
  echo -n "."
  if [[ $i -eq 12 ]]; then
    echo -e " ${CLR_GREEN}RUNNING (PID $BACKEND_PID)${CLR_RESET}"
  fi
done

# 6. Start Frontend (Vite Dev Server on port 3000) unless prod-only
if [[ "$PROD_ONLY" == "false" ]]; then
  echo -e "${CLR_GREEN}▶${CLR_RESET} Starting Vite frontend dev server on http://localhost:$FRONTEND_PORT..."
  cd "$WEB_DIR"
  npm run dev -- --port "$FRONTEND_PORT" --host 0.0.0.0 &
  FRONTEND_PID=$!

  # Wait briefly for Vite server
  echo -n "Waiting for frontend dev server..."
  for i in {1..8}; do
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      echo -e " ${CLR_RED}FAILED${CLR_RESET}"
      echo "Frontend process exited unexpectedly. Check logs above."
      exit 1
    fi
    if curl -s -f "http://127.0.0.1:$FRONTEND_PORT" >/dev/null 2>&1; then
      echo -e " ${CLR_GREEN}READY${CLR_RESET}"
      break
    fi
    sleep 0.5
    echo -n "."
    if [[ $i -eq 8 ]]; then
      echo -e " ${CLR_GREEN}RUNNING (PID $FRONTEND_PID)${CLR_RESET}"
    fi
  done
fi

# 7. Ready banner
echo ""
echo -e "${CLR_GREEN}${CLR_BOLD}==============================================================================${CLR_RESET}"
echo -e "${CLR_GREEN}${CLR_BOLD}  🎉 Evaluator AI is running locally!${CLR_RESET}"
echo -e "${CLR_GREEN}${CLR_BOLD}==============================================================================${CLR_RESET}"
if [[ "$PROD_ONLY" == "false" ]]; then
  echo -e "  👉 ${CLR_BOLD}React Web UI (Live Dev):${CLR_RESET}  ${CLR_CYAN}http://localhost:$FRONTEND_PORT${CLR_RESET}"
fi
echo -e "  👉 ${CLR_BOLD}FastAPI Web UI & Direct:${CLR_RESET}  ${CLR_CYAN}http://localhost:$BACKEND_PORT/${CLR_RESET}"
echo -e "  👉 ${CLR_BOLD}Interactive Swagger Docs:${CLR_RESET} ${CLR_CYAN}http://localhost:$BACKEND_PORT/docs${CLR_RESET}"
echo -e "  👉 ${CLR_BOLD}Server Health Status:${CLR_RESET}     ${CLR_CYAN}http://localhost:$BACKEND_PORT/healthz${CLR_RESET}"
echo -e "  👉 ${CLR_BOLD}Test Demo Audit API:${CLR_RESET}      ${CLR_CYAN}http://localhost:$BACKEND_PORT/api/audit/demo${CLR_RESET}"
echo -e "${CLR_GREEN}${CLR_BOLD}==============================================================================${CLR_RESET}"
echo -e "${CLR_DIM}Press Ctrl+C at any time to stop all services.${CLR_RESET}"
echo ""

# Optional automatic browser open
if [[ "$*" == *"--open"* ]]; then
  if command -v open >/dev/null 2>&1; then
    TARGET_URL="http://localhost:$FRONTEND_PORT"
    if [[ "$PROD_ONLY" == "true" ]]; then
      TARGET_URL="http://localhost:$BACKEND_PORT"
    fi
    open "$TARGET_URL"
  fi
fi

# Wait on background processes
wait "$BACKEND_PID" 2>/dev/null || true
