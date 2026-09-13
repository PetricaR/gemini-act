#!/usr/bin/env bash
# Deploy Hermes Agent to Cloud Run, IAM-locked, with persistent state in GCS.
#
# Hermes is a separate agent from gemini-act — its own model, loop and memory.
# This script lives here only because gemini-act is where the project's deploy
# tooling already lives; it deploys a *different* service and does not touch
# the gemini-act service.
#
# Why it is shaped this way:
#
#   - Hermes keeps ALL state in one directory: config.yaml, .env, memories/,
#     skills/, sessions/ and state.db. Cloud Run has no attachable disk, so
#     that directory is a GCS bucket mounted via FUSE at /opt/data.
#
#   - state.db is SQLite. WAL mode needs mmap and POSIX locking that GCS FUSE
#     does not provide, so config.yaml pins `database.journal_mode: delete`.
#     That file is uploaded BEFORE first boot so the database is created in the
#     right mode — an existing WAL database is never live-downgraded.
#
#   - min=max=1 is a correctness constraint, not tuning. From Hermes' own docs:
#     "Never run two Hermes gateway containers against the same data directory
#     simultaneously — session files and memory stores are not designed for
#     concurrent write access." This is why the service cannot scale to zero,
#     and therefore why it is always billed.
#
#   - --no-allow-unauthenticated is deliberate. The Hermes dashboard embeds a
#     live PTY (a real terminal) in the container, alongside shell tools and
#     whatever API keys are mounted. It must never be reachable without an
#     identity check. Reach it through the proxy command printed at the end.
#
# Prerequisites — create these two secrets first, they are not created here
# because secret material should not pass through a deploy script:
#
#   gcloud secrets create hermes-gemini-key --replication-policy=automatic \
#     --project=website-formare-ai
#   grep '^GEMINI_API_KEY=' ../../.env | cut -d= -f2- \
#     | gcloud secrets versions add hermes-gemini-key --data-file=- \
#       --project=website-formare-ai
#
#   gcloud secrets create hermes-dash-pass --replication-policy=automatic \
#     --project=website-formare-ai
#   openssl rand -base64 24 | tr -d '\n' \
#     | gcloud secrets versions add hermes-dash-pass --data-file=- \
#       --project=website-formare-ai
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT="${PROJECT:-website-formare-ai}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-hermes}"
BUCKET="${BUCKET:-hermes-data-428056592625}"
DASH_USER="${DASH_USER:-radan}"
# The only Google identity allowed through IAP. Everyone else gets a 403 at the
# edge, before a request ever reaches the container.
IAP_USER="${IAP_USER:-petrica.radan@formare.ai}"
REPO="hermes"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/hermes-agent:latest"
UPSTREAM="${UPSTREAM:-nousresearch/hermes-agent:latest}"

echo "==> project=${PROJECT} region=${REGION} service=${SERVICE}"

echo "==> enabling APIs (idempotent)"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  iap.googleapis.com \
  --project="${PROJECT}"

# The IAP service agent must exist before a service can be deployed with --iap.
# Creating it is idempotent and returns the existing one on re-runs.
echo "==> IAP service agent"
gcloud beta services identity create --service=iap.googleapis.com \
  --project="${PROJECT}" >/dev/null
IAP_SA="service-$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')@gcp-sa-iap.iam.gserviceaccount.com"

echo "==> state bucket"
gcloud storage buckets describe "gs://${BUCKET}" --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://${BUCKET}" \
    --project="${PROJECT}" --location="${REGION}" --uniform-bucket-level-access

# Must happen before the first boot: Hermes creates state.db on startup, and
# the journal mode it picks then is the one it keeps.
echo "==> seeding config.yaml into the bucket"
gcloud storage cp "${SCRIPT_DIR}/config.yaml" "gs://${BUCKET}/config.yaml" --project="${PROJECT}"

echo "==> artifact registry repo"
gcloud artifacts repositories describe "${REPO}" \
  --location="${REGION}" --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "${REPO}" \
    --repository-format=docker --location="${REGION}" --project="${PROJECT}" \
    --description="Hermes Agent images"

# Cloud Run pulls only from Artifact Registry, so the Docker Hub image has to be
# mirrored. Cloud Build does the pull and push, which is why this needs no local
# Docker daemon.
echo "==> mirroring ${UPSTREAM} -> ${IMAGE} via Cloud Build"
MIRROR_DIR="$(mktemp -d)"
trap 'rm -rf "${MIRROR_DIR}"' EXIT
printf 'FROM %s\n' "${UPSTREAM}" > "${MIRROR_DIR}/Dockerfile"
gcloud builds submit "${MIRROR_DIR}" --tag "${IMAGE}" --project="${PROJECT}"

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

# Cloud Run resolves --set-secrets as the *runtime* service account, not as the
# deploying user, so the deploy fails at revision-creation time without this.
# Granted per-secret rather than project-wide to keep the scope tight.
echo "==> granting ${RUNTIME_SA} accessor on the secrets"
for _secret in hermes-gemini-key hermes-dash-pass; do
  gcloud secrets add-iam-policy-binding "${_secret}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role=roles/secretmanager.secretAccessor \
    --project="${PROJECT}" >/dev/null
done

echo "==> deploying"
# The command is `gateway run`, NOT `dashboard`. In the official image the
# entrypoint is s6-overlay: `gateway run` becomes a `sleep infinity` heartbeat
# that keeps the container alive while s6 supervises the real processes, and the
# dashboard comes up as a supervised s6-rc service when HERMES_DASHBOARD=1.
# Running `hermes dashboard` directly would bypass that supervision tree.
#
# The web UI itself is already built into the image (the Dockerfile runs
# `npm run build` in web/), so there is no build step at boot.
#
# HERMES_DASHBOARD_HOST/PORT default to 0.0.0.0:9119 inside the container; they
# are set explicitly here because --port below has to agree with them.
#
# --no-cpu-throttling: Hermes does background work between HTTP requests, which
# a throttled instance would stall.
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --no-allow-unauthenticated \
  --iap \
  --ingress=all \
  --min-instances=1 \
  --max-instances=1 \
  --memory=4Gi \
  --cpu=2 \
  --no-cpu-throttling \
  --timeout=3600 \
  --port=9119 \
  --add-volume=name=data,type=cloud-storage,bucket="${BUCKET}" \
  --add-volume-mount=volume=data,mount-path=/opt/data \
  --set-secrets=GEMINI_API_KEY=hermes-gemini-key:latest,HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=hermes-dash-pass:latest \
  --set-env-vars=HERMES_DASHBOARD=1,HERMES_DASHBOARD_HOST=0.0.0.0,HERMES_DASHBOARD_PORT=9119,HERMES_DASHBOARD_BASIC_AUTH_USERNAME="${DASH_USER}" \
  --args="^:^gateway:run"

# IAP terminates the request itself and then calls the service as its own
# service agent, so the agent — not the end user — needs run.invoker.
echo "==> granting IAP service agent invoker on the service"
gcloud run services add-iam-policy-binding "${SERVICE}" \
  --region="${REGION}" --project="${PROJECT}" \
  --member="serviceAccount:${IAP_SA}" \
  --role=roles/run.invoker >/dev/null

# The allowlist. This is the binding that makes it "my email only": anyone else
# is refused by IAP at the edge, before the container sees the request.
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

Open that in a browser. IAP will ask you to sign in with Google and will only
let ${IAP_USER} through — every other account gets a 403 at the edge, without
reaching the container. No gcloud proxy needed.

Behind IAP, Hermes asks for its own login ('${DASH_USER}'). Read the password:

  gcloud secrets versions access latest --secret=hermes-dash-pass --project=${PROJECT}

To allow another person later:

  gcloud iap web add-iam-policy-binding --resource-type=cloud-run \\
    --service=${SERVICE} --region=${REGION} --project=${PROJECT} \\
    --member=user:THEIR_EMAIL --role=roles/iap.httpsResourceAccessor
EOF
