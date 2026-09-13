# DeepSeek Harness (dsh) Web UI driving gemini-act's imobiliare MCP tools.
#
# Two runtimes in one image on purpose: dsh is Node, the imobiliare MCP server
# is Python, and dsh speaks to it over stdio. Keeping them in one container
# avoids exposing the MCP server over the network at all — it is spawned as a
# child process and is unreachable from outside.
#
# Build context is the REPO ROOT (see cloudbuild.yaml), because the image needs
# src/gemini_act to install the imobiliare-mcp entry point.

# trixie (Debian 13), not the default bookworm: bookworm ships Python 3.11.2
# and pyproject.toml requires >=3.12, so the gemini-act install fails there
# with "requires a different Python". Trixie ships 3.13.
FROM node:24-trixie-slim

# python3 for the MCP server; git for dsh plugin installs; ca-certificates
# because the system Python on some bases ships without a CA bundle and the
# imobiliare tools make outbound HTTPS calls (see imobiliare_mcp/CLAUDE.md).
# nginx fronts dsh: dsh refuses to bind 0.0.0.0 and Cloud Run requires it, so
# dsh stays on loopback and nginx does the listening. See nginx.conf.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip git ca-certificates nginx \
    && rm -rf /var/lib/apt/lists/*

# dsh is in developer preview and its README warns of breaking changes, so pin
# this once a version is known good rather than tracking latest.
ARG DSH_VERSION=latest
RUN npm install -g "@deepseek-ai/dsh@${DSH_VERSION}"

# ---- imobiliare MCP server -------------------------------------------------
# Installed into its own venv, then the console script is linked onto PATH so
# dsh can spawn it by name. --no-deps is not used: the property tools need
# httpx, pillow, reportlab and python-docx at runtime.
WORKDIR /opt/gemini-act
COPY pyproject.toml README.md ./
COPY src/ src/
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir . \
    && ln -s /opt/venv/bin/imobiliare-mcp /usr/local/bin/imobiliare-mcp

# ---- state -----------------------------------------------------------------
# settings.yaml, .credentials.yaml, profiles/ and the generated PDF reports.
# On Cloud Run this is a GCS bucket: safe here because dsh stores YAML and the
# reports are whole-file writes — neither needs the POSIX locking GCS FUSE
# refuses. (This is what made Hermes unworkable; see ../hermes/README.md.)
ENV DSH_HOME=/opt/data
RUN mkdir -p /opt/data

COPY deploy/dsh/nginx.conf /etc/nginx/nginx.conf
COPY deploy/dsh/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /opt/data

# 8080 is nginx. dsh itself listens on 3080 bound to loopback and is never
# published — it is reachable only through nginx, which in turn is reachable
# only through IAP.
EXPOSE 8080

CMD ["/usr/local/bin/entrypoint.sh"]
