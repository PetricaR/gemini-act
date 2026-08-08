#!/usr/bin/env bash
# Build and deploy Gemini Act to Cloud Run.
#
# Chicken-and-egg note: the service's own URL is both the OAuth redirect base
# and the JWT audience Chat signs against. So we deploy once to learn the URL,
# then redeploy with it baked into the environment. Re-runs are cheap.
set -euo pipefail

# Load .env from the repo root if present. Values here win over anything
# already exported in the shell — same as running `source .env` by hand.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
# Where the Cloud Run service runs.
REGION="${CLOUD_RUN_REGION:-europe-west1}"
# Where Vertex AI serves the model. Distinct from REGION: Gemini 3.x is only
# available from the `global` endpoint, and 404s in regional ones.
VERTEX_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"
SERVICE="${SERVICE_NAME:-gemini-act}"
SA_EMAIL="${SERVICE_ACCOUNT_NAME:-gemini-act-runtime}@${PROJECT}.iam.gserviceaccount.com"
MODEL="${GEMINI_ACT_MODEL:-gemini-3.6-flash}"
# Pins the Workspace add-on token issuer, and is needed before the first deploy.
PROJECT_NUM="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
# ADK defaults GOOGLE_API_USE_CLIENT_CERTIFICATE to "true" (google-auth defaults
# it to false), so every MCP session attempts an mTLS channel that Cloud Run has
# no client certificate for. It falls back correctly but logs a warning each
# time and wastes an ADC lookup; set below in --set-env-vars.
MCP_ENABLED="${GEMINI_ACT_MCP_ENABLED:-gmail,drive,calendar}"
THINKING_LEVEL="${GEMINI_ACT_THINKING_LEVEL:-LOW}"
# Keep one instance warm. Scale-to-zero is expensive here in a way it is not for
# an ordinary service: CachingToolset holds its tool list in process memory, so
# a cold instance re-runs `tools/list` against every enabled MCP server before
# it can answer anything — 15-25s each (see agent/tools/caching_toolset.py).
# The first message after any idle period paid that. Set to 0 to trade the idle
# instance's cost back for that latency.
MIN_INSTANCES="${CLOUD_RUN_MIN_INSTANCES:-1}"

: "${GEMINI_ACT_OAUTH_CLIENT_ID:?set GEMINI_ACT_OAUTH_CLIENT_ID}"
: "${GEMINI_ACT_OAUTH_CLIENT_SECRET:?set GEMINI_ACT_OAUTH_CLIENT_SECRET}"
: "${GEMINI_ACT_STATE_SECRET:?set GEMINI_ACT_STATE_SECRET (any long random string)}"

echo "==> Deploying ${SERVICE} to ${REGION}"

# Pass 1: get the service up so we can read its URL.
#
# On --allow-unauthenticated: Cloud Run IAM cannot gate this service, because
# /oauth/callback is reached by the user's *browser*, redirected from Google,
# carrying no Google identity token — IAM would reject the OAuth flow outright.
# Authentication is enforced in the application instead, and strictly:
#   POST /    requires a Google-signed JWT issued by chat@system.gserviceaccount
#             .com whose audience equals this service's URL. See chat/auth.py;
#             it fails closed, returning 500 rather than accepting when the
#             expected audience is unset.
#   /oauth/*  requires a `state` signed with GEMINI_ACT_STATE_SECRET.
# Do not "harden" this back to --no-allow-unauthenticated: it silently breaks
# both the OAuth callback and Chat delivery.
gcloud run deploy "${SERVICE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --source="${REPO_ROOT}" \
  --service-account="${SA_EMAIL}" \
  --allow-unauthenticated \
  --memory=8Gi \
  --cpu=4 \
  --timeout=300 \
  --no-cpu-throttling \
  --min-instances="${MIN_INSTANCES}" \
  --set-env-vars="^##^GOOGLE_CLOUD_PROJECT=${PROJECT}##GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION}##GOOGLE_GENAI_USE_VERTEXAI=TRUE##GEMINI_ACT_MODEL=${MODEL}##GEMINI_ACT_THINKING_LEVEL=${THINKING_LEVEL}##GEMINI_ACT_MCP_ENABLED=${MCP_ENABLED}##GEMINI_ACT_TOKEN_STORE=firestore##GEMINI_ACT_PROJECT_NUMBER=${PROJECT_NUM}##GOOGLE_API_USE_CLIENT_CERTIFICATE=false" \
  --quiet

# Cloud Run exposes two hostnames (a legacy hashed one and the canonical
# <service>-<project-number>.<region>.run.app). status.url returns the legacy
# form, but the canonical one is what the console and `gcloud run deploy` show —
# and the OAuth redirect URI, the Chat endpoint and CHAT_AUDIENCE must all agree
# on a single hostname, so pick the canonical one deterministically.
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
URL="$(gcloud run services describe "${SERVICE}" \
  --project="${PROJECT}" --region="${REGION}" \
  --format="value(metadata.annotations['run.googleapis.com/urls'])" \
  | tr ',' '\n' | tr -d '[]"' | grep -F "${PROJECT_NUMBER}" | head -1)"
# Fall back to status.url if the annotation is ever absent.
if [ -z "${URL}" ]; then
  URL="$(gcloud run services describe "${SERVICE}" \
    --project="${PROJECT}" --region="${REGION}" --format='value(status.url)')"
fi
echo "==> Service URL: ${URL}"

# Pass 2: bake in the URL-dependent settings.
echo "==> Applying URL-dependent configuration"
gcloud run services update "${SERVICE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --update-env-vars="^##^GEMINI_ACT_CHAT_AUDIENCE=${URL}##GEMINI_ACT_PUBLIC_BASE_URL=${URL}##GEMINI_ACT_OAUTH_CLIENT_ID=${GEMINI_ACT_OAUTH_CLIENT_ID}##GEMINI_ACT_OAUTH_CLIENT_SECRET=${GEMINI_ACT_OAUTH_CLIENT_SECRET}##GEMINI_ACT_STATE_SECRET=${GEMINI_ACT_STATE_SECRET}" \
  --quiet

# Google Chat calls the endpoint as this fixed service account.
echo "==> Granting Google Chat the invoker role"
gcloud run services add-iam-policy-binding "${SERVICE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --member="serviceAccount:chat@system.gserviceaccount.com" \
  --role="roles/run.invoker" \
  --quiet >/dev/null

cat <<EOF

==> Deployed.

  Service URL          ${URL}
  OAuth redirect URI   ${URL}/oauth/callback
  Chat HTTP endpoint   ${URL}
  Health check         ${URL}/healthz

Next:
  * Add the OAuth redirect URI above to your Web OAuth client, if not already there.
  * On the Google Chat API configuration page, set the HTTP endpoint URL to the
    service URL and register the slash commands listed in README.md.
EOF
