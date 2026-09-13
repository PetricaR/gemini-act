#!/usr/bin/env bash
# Deploy DeepSeek Harness (dsh) to Cloud Run, IAP-locked, state in GCS.
#
# Replaces the earlier Hermes deployment (../hermes/), which could not work on
# Cloud Run: Hermes stores sessions in SQLite and s6-log chmods its log files,
# and GCS FUSE refuses both with EPERM. dsh keeps its state as YAML files under
# $DSH_HOME and uses no SQLite at all, so a bucket mount is sufficient.
#
# Shape notes:
#
#   - $DSH_HOME=/opt/data holds settings.yaml, .credentials.yaml and profiles/.
#     That path is the GCS bucket, so configuration survives revisions.
#
#   - max-instances=1. dsh has no coordination across processes and two
#     instances would write the same YAML files in the bucket concurrently.
#     min-instances=1 keeps it warm; drop to 0 to trade cold starts for cost.
#
#   - IAP is the ONLY gate. Unlike Hermes, the dsh web server has no built-in
#     authentication — no token, no password (packages/host/webserver). Anyone
#     who passes IAP has full agent access, so keep the allowlist short.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT="${PROJECT:-website-formare-ai}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-dsh}"
BUCKET="${BUCKET:-dsh-data-428056592625}"
IAP_USER="${IAP_USER:-petrica.radan@formare.ai}"
REPO="dsh"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/dsh:latest"

echo "==> project=${PROJECT} region=${REGION} service=${SERVICE}"

echo "==> enabling APIs (idempotent)"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  iap.googleapis.com \
  --project="${PROJECT}"

echo "==> IAP service agent"
gcloud beta services identity create --service=iap.googleapis.com \
  --project="${PROJECT}" >/dev/null
IAP_SA="service-$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')@gcp-sa-iap.iam.gserviceaccount.com"

echo "==> state bucket"
gcloud storage buckets describe "gs://${BUCKET}" --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://${BUCKET}" \
    --project="${PROJECT}" --location="${REGION}" --uniform-bucket-level-access

echo "==> artifact registry repo"
gcloud artifacts repositories describe "${REPO}" \
  --location="${REGION}" --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "${REPO}" \
    --repository-format=docker --location="${REGION}" --project="${PROJECT}" \
    --description="DeepSeek Harness images"

# Cloud Build builds the Dockerfile next to this script, so no local Docker.
echo "==> building image via Cloud Build"
gcloud builds submit "${SCRIPT_DIR}" --tag "${IMAGE}" --project="${PROJECT}"

RUNTIME_SA="$(gcloud run services describe "${SERVICE}" --region="${REGION}" \
  --project="${PROJECT}" --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"
if [[ -z "${RUNTIME_SA}" ]]; then
  RUNTIME_SA="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
fi
echo "==> granting ${RUNTIME_SA} read/write on the state bucket"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role=roles/storage.objectAdmin \
  --project="${PROJECT}" >/dev/null

echo "==> deploying"
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --no-allow-unauthenticated \
  --iap \
  --ingress=all \
  --min-instances=1 \
  --max-instances=1 \
  --memory=2Gi \
  --cpu=2 \
  --no-cpu-throttling \
  --timeout=3600 \
  --port=3080 \
  --add-volume=name=data,type=cloud-storage,bucket="${BUCKET}" \
  --add-volume-mount=volume=data,mount-path=/opt/data

echo "==> granting IAP service agent invoker on the service"
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

URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" \
  --project="${PROJECT}" --format='value(status.url)')"

cat <<EOF

Deployed.

  ${URL}

Sign in with Google; only ${IAP_USER} is allowed through. There is no second
login — dsh has no auth of its own, so IAP is the whole boundary.

First run, configure the model in the UI (Settings -> Models -> Add a custom
provider). For Gemini:

  Provider ID : gemini
  Protocol    : openai
  Base URL    : https://generativelanguage.googleapis.com/v1beta/openai
  API key     : your Gemini key
  Model       : gemini-3.8-flash

That writes \$DSH_HOME/settings.yaml and .credentials.yaml into the bucket, so
it survives revisions and restarts.
EOF
