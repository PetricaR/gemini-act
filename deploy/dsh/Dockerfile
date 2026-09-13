# DeepSeek Harness (dsh) for Cloud Run.
#
# There is no official dsh image, so this is a thin wrapper around the npm
# package. Node 24: dsh requires ^22.19 or >=24.
FROM node:24-slim

# git is used by dsh for plugin installs; ca-certificates for outbound TLS.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pin the version rather than tracking latest: dsh is in developer preview and
# its own README warns "THERE WILL BE COMPATIBILITY-BREAKING CHANGES".
ARG DSH_VERSION=latest
RUN npm install -g "@deepseek-ai/dsh@${DSH_VERSION}"

# All mutable state lives here: settings.yaml, .credentials.yaml, profiles/.
# On Cloud Run this path is a GCS bucket mounted via FUSE. Unlike Hermes this
# is safe — dsh stores YAML files and uses no SQLite, so it needs none of the
# POSIX locking that GCS FUSE refuses.
ENV DSH_HOME=/opt/data
RUN mkdir -p /opt/data

# Cloud Run sends traffic to $PORT; 3080 is the dsh default and is set
# explicitly on the deploy so the two agree.
EXPOSE 3080

# --host 0.0.0.0 is required in a container: the default 127.0.0.1 would not be
# reachable from outside it. The web server validates this flag against exactly
# these two literals.
# --no-open: there is no browser to open in a container.
CMD ["dsh", "web", "--host", "0.0.0.0", "--port", "3080", "--no-open"]
