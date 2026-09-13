#!/usr/bin/env bash
# Deploy the DeepSeek Harness (dsh) Web UI wired to gemini-act's imobiliare MCP
# tools, on Cloud Run, IAP-locked, with state in GCS.
#
# What this gives you: the dsh Web UI, a model of your choosing driving the
# conversation, and all 18 imobiliare tools available as native tools. What it
# is NOT: the gemini-act ADK agent. Its system prompt, A2UI cards, Chat
# streaming and per-user Workspace OAuth are not involved — only the MCP tools
# are shared. See README.md.
#
# Replaces the Hermes attempt (../hermes/), which could not work on Cloud Run:
# Hermes stores sessions in SQLite and s6-log chmods its logs, and GCS FUSE
# refuses both with EPERM. dsh's default bundle uses storage-json rather than
# storage-sqlite, so it avoids the SQLite half — but NOT the chmod half: it
# refuses to boot unless .credentials.yaml is owner-only. That is why the volume
# below sets mount-options rather than taking the GCS FUSE defaults.
#
#   - max-instances=1: dsh has no cross-process coordination and two instances
#     would write the same YAML in the bucket concurrently.
#   - IAP is the EFFECTIVE sole gate. dsh does have auth of its own — a launch
#     token, regenerated per process (an in-memory Map in
#     packages/client/connection/src/browser-auth.ts) — but entrypoint.sh reads
#     that token and has nginx hand it to every caller, so it stops being an
#     independent control. Anyone IAP admits gets a fully tool-enabled agent
#     that can execute code. Keep the allowlist to the people you mean.
#
# Prerequisites — create these secrets first (values from ../../.env):
#
#   PROJECT=website-formare-ai
#   for pair in \
#     "dsh-gemini-key:GEMINI_API_KEY" \
#     "dsh-maps-key:GEMINI_ACT_MAPS_API_KEY" \
#     "dsh-targetare-key:GEMINI_ACT_TARGETARE_API_KEY"; do
#     name="${pair%%:*}"; var="${pair##*:}"
#     gcloud secrets create "$name" --replication-policy=automatic --project=$PROJECT 2>/dev/null
#     grep "^${var}=" ../../.env | cut -d= -f2- \
#       | gcloud secrets versions add "$name" --data-file=- --project=$PROJECT
#   done
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PROJECT="${PROJECT:-website-formare-ai}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-dsh}"
BUCKET="${BUCKET:-dsh-data-428056592625}"
IAP_USER="${IAP_USER:-petrica.radan@formare.ai}"
# Authorities dsh accepts on its /api Host/Origin fence. Both hostnames this
# service answers on; without them every /api call is refused 403 behind the
# proxy. Comma-separated, which is why the --set-env-vars below uses gcloud's
# ^@^ custom delimiter — a comma there would start a second variable.
TRUSTED_HOSTS="${TRUSTED_HOSTS:-dsh-428056592625.europe-west1.run.app,dsh-dyeutedtjq-ew.a.run.app}"
REPO="dsh"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/dsh:latest"

echo "==> project=${PROJECT} region=${REGION} service=${SERVICE}"

echo "==> enabling APIs (idempotent)"
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  storage.googleapis.com secretmanager.googleapis.com iap.googleapis.com \
  --project="${PROJECT}"

echo "==> IAP service agent"
gcloud beta services identity create --service=iap.googleapis.com \
  --project="${PROJECT}" >/dev/null
PROJECT_NUM="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
IAP_SA="service-${PROJECT_NUM}@gcp-sa-iap.iam.gserviceaccount.com"

echo "==> state bucket"
gcloud storage buckets describe "gs://${BUCKET}" --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://${BUCKET}" \
    --project="${PROJECT}" --location="${REGION}" --uniform-bucket-level-access

# Seeded before first boot so the MCP server is registered on the very first
# run. dsh applies the home-level patch after each profile's own patch layer.
echo "==> seeding cordis.patch.yml (registers the imobiliare MCP server)"
gcloud storage cp "${SCRIPT_DIR}/cordis.patch.yml" \
  "gs://${BUCKET}/cordis.patch.yml" --project="${PROJECT}"

echo "==> artifact registry repo"
gcloud artifacts repositories describe "${REPO}" \
  --location="${REGION}" --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "${REPO}" \
    --repository-format=docker --location="${REGION}" --project="${PROJECT}" \
    --description="DeepSeek Harness images"

# Context is the repo root: the image installs src/gemini_act for the
# imobiliare-mcp entry point. Hence a build config rather than --tag.
echo "==> building image via Cloud Build (context: repo root)"
gcloud builds submit "${REPO_ROOT}" \
  --config="${SCRIPT_DIR}/cloudbuild.yaml" \
  --substitutions=_IMAGE="${IMAGE}" \
  --project="${PROJECT}"

RUNTIME_SA="${PROJECT_NUM}-compute@developer.gserviceaccount.com"

echo "==> granting ${RUNTIME_SA} read/write on the state bucket"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role=roles/storage.objectAdmin --project="${PROJECT}" >/dev/null

# --set-secrets is resolved by the RUNTIME service account when the revision
# boots, not by the deploying user, so these grants are required or the deploy
# fails at revision creation.
echo "==> granting ${RUNTIME_SA} accessor on the secrets"
for _secret in dsh-gemini-key dsh-maps-key dsh-targetare-key; do
  gcloud secrets add-iam-policy-binding "${_secret}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role=roles/secretmanager.secretAccessor \
    --project="${PROJECT}" >/dev/null
done

echo "==> deploying"
# On the volume's mount-options below: these are not tuning. GCS FUSE
# synthesizes POSIX modes from mount flags (the objects carry no real mode) and
# defaults to file-mode=666. dsh then refuses to boot, because credentials-local
# asserts .credentials.yaml is owner-only and cannot chmod it — GCS FUSE rejects
# chmod outright. uid/gid=0 match the container user so ownership agrees too.
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --no-allow-unauthenticated \
  --iap \
  --ingress=all \
  --min-instances=1 --max-instances=1 \
  --memory=2Gi --cpu=2 \
  --no-cpu-throttling \
  --timeout=3600 \
  --port=8080 \
  --add-volume="name=data,type=cloud-storage,bucket=${BUCKET},mount-options=uid=0;gid=0;file-mode=600;dir-mode=700" \
  --add-volume-mount=volume=data,mount-path=/opt/data \
  --set-secrets=GEMINI_API_KEY=dsh-gemini-key:latest,GEMINI_ACT_MAPS_API_KEY=dsh-maps-key:latest,GEMINI_ACT_TARGETARE_API_KEY=dsh-targetare-key:latest \
  --set-env-vars="^@^GEMINI_ACT_IMOBILIARE_SESSION_ID=cloudrun@DSH_TRUSTED_HOSTS=${TRUSTED_HOSTS}"

echo "==> granting IAP service agent invoker on the service"
gcloud run services add-iam-policy-binding "${SERVICE}" \
  --region="${REGION}" --project="${PROJECT}" \
  --member="serviceAccount:${IAP_SA}" \
  --role=roles/run.invoker >/dev/null

echo "==> granting ${IAP_USER} access through IAP"
gcloud iap web add-iam-policy-binding \
  --resource-type=cloud-run --service="${SERVICE}" \
  --region="${REGION}" --project="${PROJECT}" \
  --member="user:${IAP_USER}" \
  --role=roles/iap.httpsResourceAccessor >/dev/null

URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" \
  --project="${PROJECT}" --format='value(status.url)')"

cat <<EOF

Deployed.

  ${URL}

Sign in with Google; only ${IAP_USER} passes. There is no second login — dsh
has no auth of its own, so IAP is the whole boundary.

First run, set the model in Settings -> Models -> Add a custom provider:

  Provider ID : gemini
  Protocol    : openai
  Base URL    : https://generativelanguage.googleapis.com/v1beta/openai
  Model       : gemini-3.8-flash

Then confirm the tools arrived — ask the agent to list its tools, or look for
names beginning mcp__imobiliare__ (cauta, evaluare, inspecteaza_poze,
genereaza_raport_complet_pdf, ...). If they are missing, check the logs for the
MCP client failing to spawn 'imobiliare-mcp'.
EOF
