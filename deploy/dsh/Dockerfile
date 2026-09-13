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
# DSH_HOME is the container's REAL filesystem, deliberately NOT the GCS mount.
# dsh needs POSIX semantics the mount cannot provide: session persistence and
# the attachment store publish files with link()
# (session-persistence-jsonl/src/index.ts:1137, attachment-local/src/store.ts)
# and GCS FUSE answers ENOSYS to hard links, with no fallback path. It also
# refuses chmod, which dsh requires on .credentials.yaml before it will boot.
#
# The bucket is mounted separately at /opt/seed and carries only the config
# worth keeping. entrypoint.sh restores it into DSH_HOME at boot and copies it
# back as it changes; sessions and attachments are deliberately ephemeral.
ENV DSH_HOME=/opt/dsh
ENV DSH_SEED_DIR=/opt/seed
RUN mkdir -p /opt/dsh /opt/seed && chmod 700 /opt/dsh

COPY deploy/dsh/nginx.conf /etc/nginx/nginx.conf
COPY deploy/dsh/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /opt/dsh

# 8080 is nginx. dsh itself listens on 3080 bound to loopback and is never
# published — it is reachable only through nginx, which in turn is reachable
# only through IAP.
EXPOSE 8080

CMD ["/usr/local/bin/entrypoint.sh"]
