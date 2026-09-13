#!/usr/bin/env bash
# Container entrypoint: dsh on loopback, nginx facing Cloud Run.
#
# Order matters. nginx is started only after dsh is accepting connections, so
# Cloud Run's startup probe against :8080 does not succeed while dsh is still
# booting — otherwise the revision goes healthy and then 502s real traffic.
set -euo pipefail

DSH_PORT="${DSH_PORT:-3080}"

echo "[entrypoint] starting dsh on 127.0.0.1:${DSH_PORT}"
dsh web --host 127.0.0.1 --port "${DSH_PORT}" --no-open &
DSH_PID=$!

# If dsh dies, take the container down with it rather than serving 502s
# forever behind a healthy-looking nginx.
trap 'kill -TERM "${DSH_PID}" 2>/dev/null || true' TERM INT

echo "[entrypoint] waiting for dsh to listen"
for _i in $(seq 1 120); do
  if ! kill -0 "${DSH_PID}" 2>/dev/null; then
    echo "[entrypoint] dsh exited during startup" >&2
    wait "${DSH_PID}" || true
    exit 1
  fi
  # bash's /dev/tcp probe avoids adding curl or netcat to the image.
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

echo "[entrypoint] starting nginx on 0.0.0.0:8080"
exec nginx -c /etc/nginx/nginx.conf -g 'daemon off;'
