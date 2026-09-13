#!/usr/bin/env bash
# Deploy the ADK dev web UI (`adk web`) to Cloud Run, IAP-locked.
#
# This is the UI `make dev` gives you locally, running in the cloud against the
# same agent. It is a SECOND Cloud Run service and never touches the
# `gemini-act` Chat webhook service, which keeps its own URL — and has to, since
# that URL is both its JWT audience and its OAuth redirect base.
#
# Five decisions worth understanding before changing anything:
#
#   1. It reuses the repo's own image instead of `adk deploy cloud_run`.
#      That command generates its own Dockerfile, which copies only the agent
#      folder and installs only google-adk. This agent imports `gemini_act`
#      from src/ and shells out to the obscura browser binary, so that image
#      dies on the first import. The root Dockerfile already builds all of it;
#      this deploys the same image with a different command (--command/--args).
#
#   2. IAP, not --allow-unauthenticated. The ADK dev UI has no authentication
#      of its own and ADK's own help calls it development-only. Anyone who can
#      open the URL can run the agent: this project's Vertex quota, the Maps
#      key, every tool the agent has. IAP puts a Google sign-in at the edge and
#      lets exactly one identity through. Note the inversion it creates — IAP
#      terminates the request and calls the service as *itself*, so
#      roles/run.invoker belongs to the IAP service agent, not to you, and
#      --ingress=all is required: IAP is the gate, not network reachability.
#
#   3. min=max=1 is correctness, not tuning. Sessions are in memory
#      (--session_service_uri=memory://), so a second instance would show a
#      different, empty session list and a scale-to-zero would drop the
#      conversation you are in. It also makes --session-affinity unnecessary
#      for the live/bidi WebSocket. The cost of that is an always-on instance.
#
#   4. PDFs land in GCS. The report generator writes to `paths.reports_dir()`,
#      which honours IMOBILIARE_REPORTS_DIR; that points into a bucket mounted
#      through gcsfuse, so a finished report is an object in the bucket rather
#      than a file on a container filesystem that vanishes with the instance.
#      The image *cache* deliberately stays on local /tmp — it is dozens of
#      listing photos per valuation, and pushing those through FUSE would be
#      slow to no purpose. ADK artifacts go to the same bucket, under ADK's own
#      app/user/session prefixes.
#
#   5. The IMOBILIARE_* pacing is set a little slower here than the local
#      default (1.5s against 1.2s between calls to one host). Cloud Run egresses
#      from a shared Google address pool rather than from an office IP, so the
#      address this service appears as is one it does not control and may not
#      arrive with a clean reputation. See imobiliare_mcp/throttle.py.
#
#   6. --timeout=3600 is for the live (bidi streaming) socket. Cloud Run closes
#      a request at the timeout whether or not it is a WebSocket, and 3600 is
#      the maximum; a live session is one long-lived request.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
REGION="${CLOUD_RUN_REGION:-europe-west1}"
# Distinct from REGION: Gemini 3.x is served only from the `global` Vertex
# endpoint and 404s in regional ones.
VERTEX_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"
SERVICE="${ADK_UI_SERVICE:-gemini-act-adk-ui}"
SA_EMAIL="${SERVICE_ACCOUNT_NAME:-gemini-act-runtime}@${PROJECT}.iam.gserviceaccount.com"
MODEL="${GEMINI_ACT_MODEL:-gemini-3.8-flash}"
THINKING_LEVEL="${GEMINI_ACT_THINKING_LEVEL:-LOW}"
PROJECT_NUM="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
# Reports and ADK artifacts. Bucket names are global, hence the project number.
BUCKET="${ADK_UI_BUCKET:-gemini-act-rapoarte-${PROJECT_NUM}}"
# The single Google identity allowed through IAP. Everyone else gets a 403 at
# the edge, without reaching the container.
IAP_USER="${IAP_USER:-petrica.radan@formare.ai}"
# Where the bucket is mounted inside the container, and the subdirectory of it
# the PDF generator stages into.
MOUNT_PATH="/mnt/gcs"
REPORTS_DIR="${MOUNT_PATH}/rapoarte"

echo "==> project=${PROJECT} region=${REGION} service=${SERVICE} bucket=${BUCKET}"

echo "==> enabling APIs (idempotent)"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  storage.googleapis.com \
  iap.googleapis.com \
  --project="${PROJECT}" >/dev/null

# The IAP service agent has to exist before a service can be deployed with
# --iap. Creating it is idempotent and returns the existing one on re-runs.
echo "==> IAP service agent"
gcloud beta services identity create --service=iap.googleapis.com \
  --project="${PROJECT}" >/dev/null
IAP_SA="service-${PROJECT_NUM}@gcp-sa-iap.iam.gserviceaccount.com"

echo "==> reports bucket"
gcloud storage buckets describe "gs://${BUCKET}" --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://${BUCKET}" \
    --project="${PROJECT}" --location="${REGION}" --uniform-bucket-level-access

echo "==> granting ${SA_EMAIL} read/write on the bucket"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role=roles/storage.objectAdmin \
  --project="${PROJECT}" >/dev/null

echo "==> deploying"
# The '^|^' prefix sets '|' as the argument delimiter. Not the more obvious ':' —
# two of the arguments below are URIs ('memory://', 'gs://...') and would be split
# apart by a ':' delimiter into arguments adk cannot parse.
# --command/--args replace the image's CMD (the Chat webhook's uvicorn) with the
# ADK dev server. The port is hardcoded rather than read from ${PORT} because
# exec form does no shell expansion; --port below keeps Cloud Run in agreement.
#
# memory:// sessions: ADK's default here would be local storage — a SQLite file
# written next to the agent inside the container, which is both ephemeral and
# wrong the moment there is more than one instance. GCS artifacts: so a file the
# agent produces outlives the instance.
gcloud run deploy "${SERVICE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --source="${REPO_ROOT}" \
  --service-account="${SA_EMAIL}" \
  --no-allow-unauthenticated \
  --iap \
  --ingress=all \
  --port=8080 \
  --memory=8Gi \
  --cpu=4 \
  --no-cpu-throttling \
  --timeout=3600 \
  --min-instances=1 \
  --max-instances=1 \
  --add-volume=name=gcs,type=cloud-storage,bucket="${BUCKET}" \
  --add-volume-mount=volume=gcs,mount-path="${MOUNT_PATH}" \
  --command=adk \
  --args="^|^web|--host|0.0.0.0|--port|8080|--session_service_uri|memory://|--artifact_service_uri|gs://${BUCKET}|/app/agents" \
  --set-env-vars="^##^GOOGLE_CLOUD_PROJECT=${PROJECT}##GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION}##GOOGLE_GENAI_USE_VERTEXAI=TRUE##GEMINI_ACT_MODEL=${MODEL}##GEMINI_ACT_THINKING_LEVEL=${THINKING_LEVEL}##GEMINI_ACT_TOKEN_STORE=memory##GEMINI_ACT_PROJECT_NUMBER=${PROJECT_NUM}##GOOGLE_API_USE_CLIENT_CERTIFICATE=false##IMOBILIARE_REPORTS_DIR=${REPORTS_DIR}##IMOBILIARE_CACHE_DIR=/tmp/imobiliare-cache##IMOBILIARE_MIN_INTERVAL=${IMOBILIARE_MIN_INTERVAL:-1.5}##IMOBILIARE_JITTER=${IMOBILIARE_JITTER:-0.8}##IMOBILIARE_MAX_PARALLEL=${IMOBILIARE_MAX_PARALLEL:-2}##GEMINI_API_KEY=${GEMINI_API_KEY:-}##GEMINI_ACT_MAPS_API_KEY=${GEMINI_ACT_MAPS_API_KEY:-}##GEMINI_ACT_IMOBILIARE_SESSION_ID=${GEMINI_ACT_IMOBILIARE_SESSION_ID:-}" \
  --quiet

# IAP terminates the request itself and then calls the service as its own
# service agent, so the agent — not the end user — needs run.invoker.
echo "==> granting the IAP service agent invoker on the service"
gcloud run services add-iam-policy-binding "${SERVICE}" \
  --region="${REGION}" --project="${PROJECT}" \
  --member="serviceAccount:${IAP_SA}" \
  --role=roles/run.invoker >/dev/null

echo "==> granting ${IAP_USER} access through IAP"
gcloud iap web add-iam-policy-binding \
  --resource-type=cloud-run \
  --service="${SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --member="user:${IAP_USER}" \
  --role=roles/iap.httpsResourceAccessor >/dev/null

# Cloud Run answers on two hostnames: a legacy hashed one, which status.url
# returns, and the canonical <service>-<project-number>.<region>.run.app that
# the console and `gcloud run deploy` print. Both work and both are behind IAP;
# print the canonical one so it matches what you see everywhere else.
URL="https://${SERVICE}-${PROJECT_NUM}.${REGION}.run.app"

cat <<EOF

==> Deployed.

  ADK web UI     ${URL}
  Reports        gs://${BUCKET}/rapoarte/
  ADK artifacts  gs://${BUCKET}/  (under ADK's app/user/session prefixes)

Open the URL in a browser. IAP asks for a Google sign-in and only lets
${IAP_USER} through; every other account gets a 403 at the edge. No gcloud
proxy needed.

To let someone else in:

  gcloud iap web add-iam-policy-binding --resource-type=cloud-run \\
    --service=${SERVICE} --region=${REGION} --project=${PROJECT} \\
    --member=user:THEIR_EMAIL --role=roles/iap.httpsResourceAccessor

Workspace tools (Gmail/Drive/Calendar) are absent here by design: this runs the
agent anonymously, the same as \`make dev\`, so there is no Chat user and no
per-user OAuth token to give the Workspace MCP toolsets. Business, Maps and
imobiliare tools all work.
EOF
