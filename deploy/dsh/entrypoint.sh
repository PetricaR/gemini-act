#!/usr/bin/env bash
# Container entrypoint: dsh on loopback, nginx facing Cloud Run.
#
# Order matters. nginx starts only after dsh accepts connections, so Cloud
# Run's startup probe against :8080 cannot pass while dsh is still booting —
# otherwise the revision goes healthy and then 502s real traffic.
#
# It also lifts dsh's launch token out of dsh's own stdout and bakes it into
# the nginx config, so a bare GET / redirects to /?token=<token> and the
# operator never has to paste it. The token is per-process (an in-memory Map in
# packages/client/connection/src/browser-auth.ts), so it changes on every
# restart and cannot be pinned in advance.
#
# SECURITY: this makes IAP the effective sole gate. That is deliberate — IAP
# authenticates a Google identity and admits only principals holding
# roles/iap.httpsResourceAccessor. If that allowlist is ever widened, the token
# no longer adds anything, because the proxy hands it to whoever gets through.
set -euo pipefail

DSH_PORT="${DSH_PORT:-3080}"
DSH_LOG=/tmp/dsh-boot.log
DSH_HOME="${DSH_HOME:-/opt/dsh}"
SEED_DIR="${DSH_SEED_DIR:-/opt/seed}"

# Only these persist. Everything else under DSH_HOME — sessions, attachments,
# storages — stays on the container filesystem because the GCS mount cannot
# support it: link() returns ENOSYS there, which is what breaks session writes.
SEEDED_FILES=(.credentials.yaml settings.yaml cordis.patch.yml)

restore_seed() {
  local f
  for f in "${SEEDED_FILES[@]}"; do
    if [[ -f "${SEED_DIR}/${f}" ]]; then
      cp "${SEED_DIR}/${f}" "${DSH_HOME}/${f}" 2>/dev/null || true
      echo "[entrypoint] restored ${f}"
    fi
  done
  # Now on a real filesystem, so this actually takes effect — dsh refuses to
  # boot unless .credentials.yaml is owner-only.
  [[ -f "${DSH_HOME}/.credentials.yaml" ]] && chmod 600 "${DSH_HOME}/.credentials.yaml"
  chmod 700 "${DSH_HOME}" 2>/dev/null || true
  return 0
}

persist_seed() {
  local f
  for f in "${SEEDED_FILES[@]}"; do
    [[ -f "${DSH_HOME}/${f}" ]] && cp "${DSH_HOME}/${f}" "${SEED_DIR}/${f}" 2>/dev/null || true
  done
  return 0
}

mkdir -p "${DSH_HOME}"
restore_seed

# Every /api request passes a Host/Origin fence
# (packages/client/connection/src/api-request-trust.ts) that only admits
# loopback, deployment LAN literals, or an authority declared here. Behind a
# proxy the browser's Host is the public hostname, so without these every /api
# call is refused 403 while static assets still load. Comma-separated;
# entries are bare host or host:port.
TRUST_ARGS=()
if [[ -n "${DSH_TRUSTED_HOSTS:-}" ]]; then
  IFS=',' read -ra _hosts <<< "${DSH_TRUSTED_HOSTS}"
  for _h in "${_hosts[@]}"; do
    [[ -n "${_h}" ]] && TRUST_ARGS+=(--trusted-host "${_h}")
  done
  echo "[entrypoint] trusted hosts: ${DSH_TRUSTED_HOSTS}"
else
  echo "[entrypoint] WARNING: DSH_TRUSTED_HOSTS unset; /api will 403 behind a proxy" >&2
fi

echo "[entrypoint] starting dsh on 127.0.0.1:${DSH_PORT}"
# tee so the token can be read here while the output still reaches Cloud Run.
# The ${x[@]+"${x[@]}"} form keeps an empty array from tripping `set -u`.
dsh web --host 127.0.0.1 --port "${DSH_PORT}" --no-open \
  ${TRUST_ARGS[@]+"${TRUST_ARGS[@]}"} > >(tee "${DSH_LOG}") 2>&1 &
DSH_PID=$!

# Copy config back before dying so anything changed in the UI survives. Cloud
# Run sends SIGTERM with a short grace period; three small files fit easily.
trap 'persist_seed; kill -TERM "${DSH_PID}" 2>/dev/null || true' TERM INT

# SIGKILL leaves no chance to run the trap, so also persist periodically.
# Cheap: three file copies, and only when they differ.
( while sleep 30; do persist_seed; done ) &

echo "[entrypoint] waiting for dsh to listen"
for _i in $(seq 1 120); do
  if ! kill -0 "${DSH_PID}" 2>/dev/null; then
    echo "[entrypoint] dsh exited during startup" >&2
    wait "${DSH_PID}" || true
    exit 1
  fi
  if (exec 3<>"/dev/tcp/127.0.0.1/${DSH_PORT}") 2>/dev/null; then
    exec 3<&- 2>/dev/null || true
    echo "[entrypoint] dsh is up after ${_i}s"
    break
  fi
  sleep 1
done

if ! (exec 3<>"/dev/tcp/127.0.0.1/${DSH_PORT}") 2>/dev/null; then
  echo "[entrypoint] dsh did not listen within 120s" >&2
  exit 1
fi
exec 3<&- 2>/dev/null || true

# The banner line looks like:  dsh web: http://127.0.0.1:3080/?token=XXXX
echo "[entrypoint] reading the launch token"
TOKEN=""
for _i in $(seq 1 30); do
  TOKEN="$(grep -ohE 'token=[A-Za-z0-9_-]+' "${DSH_LOG}" 2>/dev/null | head -n1 | cut -d= -f2 || true)"
  [[ -n "${TOKEN}" ]] && break
  sleep 1
done

if [[ -z "${TOKEN}" ]]; then
  echo "[entrypoint] WARNING: no launch token found in dsh output" >&2
else
  # Print the sign-in URL against the public hostname so it can be opened
  # directly. dsh prints it against 127.0.0.1, which is not reachable from a
  # browser here. Log-only: nginx no longer injects the token (see nginx.conf).
  _public="${DSH_TRUSTED_HOSTS%%,*}"
  echo "[entrypoint] sign-in URL: https://${_public}/?token=${TOKEN}"
fi

echo "[entrypoint] starting nginx on 0.0.0.0:8080"
exec nginx -c /etc/nginx/nginx.conf -g 'daemon off;'
