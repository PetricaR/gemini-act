#!/usr/bin/env bash
# Deploy the valuation service: the React report API plus a real MCP endpoint.
#
# Second Cloud Run service, same image as the Chat agent, different entrypoint
# (`imobiliare-http` instead of the Dockerfile's CMD). The split is by
# deployment, not by protocol: the Chat agent still calls the valuation in
# process — see `src/imobiliare/app.py` for why — while this service exists so
# the heavy dependencies and the minutes a valuation spends get their own CPU,
# memory and blast radius, and so `/mcp` can serve clients we do not control.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
REGION="${CLOUD_RUN_REGION:-europe-west1}"
VERTEX_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"
SERVICE="${IMOBILIARE_SERVICE_NAME:-imobiliare}"
SA_EMAIL="${SERVICE_ACCOUNT_NAME:-gemini-act-runtime}@${PROJECT}.iam.gserviceaccount.com"
# Where generated reports are kept. /tmp on Cloud Run is instance-local and in
# memory, so without a bucket a report exists only for the request that made it
# and no MCP client can ever open it. `deploy/setup_gcp.sh` creates this bucket.
REPORTS_BUCKET="${IMOBILIARE_REPORTS_BUCKET:-${PROJECT}-imobiliare-rapoarte}"

# Fails closed rather than publishing 28 money-spending tools to the internet.
# The middleware in `imobiliare/app.py` refuses /mcp with 503 when this is
# empty, so a deploy that forgets it loses MCP, not its wallet.
if [[ -z "${IMOBILIARE_MCP_TOKEN:-}" ]]; then
  cat >&2 <<'EOF'
IMOBILIARE_MCP_TOKEN is not set, so /mcp would deploy disabled (503).
Generate one and put it in .env:

  echo "IMOBILIARE_MCP_TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" >> .env

Re-run with IMOBILIARE_MCP_ALLOW_DISABLED=1 to deploy without MCP anyway.
EOF
  [[ "${IMOBILIARE_MCP_ALLOW_DISABLED:-}" == "1" ]] || exit 1
fi

echo "==> Deploying ${SERVICE} to ${REGION}"

# On --allow-unauthenticated: the React report is opened by a browser, which
# carries no Google identity token, so Cloud Run IAM cannot gate this service
# without breaking the UI. /mcp is gated in the application by bearer token
# instead; everything else here is the same public report API that the Chat
# service already serves today.
gcloud run deploy "${SERVICE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --source="${REPO_ROOT}" \
  --service-account="${SA_EMAIL}" \
  --allow-unauthenticated \
  --command=imobiliare-http \
  --memory=8Gi \
  --cpu=4 \
  --timeout=900 \
  --no-cpu-throttling \
  --min-instances="${IMOBILIARE_MIN_INSTANCES:-0}" \
  --set-env-vars="^##^GOOGLE_CLOUD_PROJECT=${PROJECT}##GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION}##GOOGLE_GENAI_USE_VERTEXAI=TRUE##GOOGLE_API_USE_CLIENT_CERTIFICATE=false##IMOBILIARE_MCP_TOKEN=${IMOBILIARE_MCP_TOKEN:-}##IMOBILIARE_DRIVE_FOLDER_ID=${IMOBILIARE_DRIVE_FOLDER_ID:-}##IMOBILIARE_DRIVE_MAX_PAGINI_OCR=${IMOBILIARE_DRIVE_MAX_PAGINI_OCR:-30}##IMOBILIARE_REPORTS_DIR=${IMOBILIARE_REPORTS_DIR:-/tmp/imobiliare-rapoarte}##IMOBILIARE_CACHE_DIR=/tmp/imobiliare-cache##IMOBILIARE_REPORTS_BUCKET=${REPORTS_BUCKET}##IMOBILIARE_REPORTS_URL_TTL_DAYS=${IMOBILIARE_REPORTS_URL_TTL_DAYS:-7}##GEMINI_ACT_MAPS_API_KEY=${GEMINI_ACT_MAPS_API_KEY:-}##GEMINI_ACT_IMOBILIARE_SESSION_ID=${GEMINI_ACT_IMOBILIARE_SESSION_ID:-}##GEMINI_API_KEY=${GEMINI_API_KEY:-}" \
  --quiet

URL="$(gcloud run services describe "${SERVICE}" \
  --project="${PROJECT}" --region="${REGION}" --format='value(status.url)')"

# No IMOBILIARE_DRIVE_IMPERSONATE here on purpose: the runtime account reads the
# folder by self-impersonating, which `deploy/setup_gcp.sh` already grants.
# Setting it locally is a developer workaround for the fact that
# `gcloud auth application-default login --scopes=...drive.readonly` is refused
# for the restricted Drive scope.

cat <<EOF

==> ${SERVICE} deployed
    Report UI : ${URL}
    Report API: ${URL}/api/audit/demo
    MCP       : ${URL}/mcp   (Authorization: Bearer \$IMOBILIARE_MCP_TOKEN)
    Reports   : gs://${REPORTS_BUCKET}  (returned as signed links, ${IMOBILIARE_REPORTS_URL_TTL_DAYS:-7}d)

    Point an external MCP client at ${URL}/mcp with that bearer token.
    The Chat agent is unchanged and still calls the valuation in process.
EOF
