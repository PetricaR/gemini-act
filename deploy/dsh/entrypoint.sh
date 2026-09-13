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

trap 'kill -TERM "${DSH_PID}" 2>/dev/null || true' TERM INT

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
  # Not fatal: the UI still works if the operator supplies ?token= by hand.
  echo "[entrypoint] WARNING: no launch token found; auto-login disabled" >&2
  sed -i 's|__DSH_AUTOLOGIN_QS__||' /etc/nginx/nginx.conf
else
  echo "[entrypoint] auto-login enabled (token length ${#TOKEN})"
  # Becomes the query string on the upstream URI, so "/" is proxied as
  # "/?token=...". An internal rewrite, not a browser redirect — see nginx.conf.
  sed -i "s|__DSH_AUTOLOGIN_QS__|?token=${TOKEN}|" /etc/nginx/nginx.conf
fi

echo "[entrypoint] starting nginx on 0.0.0.0:8080"
exec nginx -c /etc/nginx/nginx.conf -g 'daemon off;'
