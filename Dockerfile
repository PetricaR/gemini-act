FROM python:3.12-slim

# uv gives us a fast, lockfile-exact install.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

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

EXPOSE 8080
CMD ["sh", "-c", "uvicorn gemini_act.chat.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
