# Stage 1: Build the React Web UI
FROM node:20-slim AS frontend-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: Python Backend with FastAPI & uv
FROM python:3.12-slim

# uv gives us a fast, lockfile-exact install.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install obscura headless browser
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends curl tar ca-certificates && \
    case "${TARGETARCH:-amd64}" in \
      "arm64") URL="https://github.com/h4ckf0r0day/obscura/releases/latest/download/obscura-aarch64-linux.tar.gz" ;; \
      *) URL="https://github.com/h4ckf0r0day/obscura/releases/latest/download/obscura-x86_64-linux.tar.gz" ;; \
    esac && \
    curl -fsSL "$URL" -o /tmp/obscura.tar.gz && \
    tar -xzf /tmp/obscura.tar.gz -C /usr/local/bin/ && \
    chmod +x /usr/local/bin/obscura* && \
    rm -rf /tmp/obscura.tar.gz /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so a source-only change does not invalidate this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
COPY agents/ ./agents/
RUN uv sync --frozen --no-dev

# Copy compiled React UI from frontend-build stage
COPY --from=frontend-build /web/dist /app/web/dist

EXPOSE 8080
CMD ["sh", "-c", "uvicorn gemini_act.chat.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
