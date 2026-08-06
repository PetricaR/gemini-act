#!/usr/bin/env bash
# Build and deploy Gemini Act to Cloud Run.
#
# Chicken-and-egg note: the service's own URL is both the OAuth redirect base
# and the JWT audience Chat signs against. So we deploy once to learn the URL,
# then redeploy with it baked into the environment. Re-runs are cheap.
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${SERVICE_NAME:-gemini-act}"
SA_EMAIL="${SERVICE_ACCOUNT_NAME:-gemini-act-runtime}@${PROJECT}.iam.gserviceaccount.com"
MODEL="${GEMINI_ACT_MODEL:-gemini-2.5-flash}"
MCP_ENABLED="${GEMINI_ACT_MCP_ENABLED:-gmail,drive,calendar,chat,docs}"

: "${GEMINI_ACT_OAUTH_CLIENT_ID:?set GEMINI_ACT_OAUTH_CLIENT_ID}"
: "${GEMINI_ACT_OAUTH_CLIENT_SECRET:?set GEMINI_ACT_OAUTH_CLIENT_SECRET}"
: "${GEMINI_ACT_STATE_SECRET:?set GEMINI_ACT_STATE_SECRET (any long random string)}"

echo "==> Deploying ${SERVICE} to ${REGION}"

# Pass 1: get the service up so we can read its URL.
gcloud run deploy "${SERVICE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --source=. \
  --service-account="${SA_EMAIL}" \
  --no-allow-unauthenticated \
  --memory=1Gi \
  --timeout=300 \
  --set-env-vars="^##^GOOGLE_CLOUD_PROJECT=${PROJECT}##GOOGLE_CLOUD_LOCATION=${REGION}##GOOGLE_GENAI_USE_VERTEXAI=TRUE##GEMINI_ACT_MODEL=${MODEL}##GEMINI_ACT_MCP_ENABLED=${MCP_ENABLED}##GEMINI_ACT_TOKEN_STORE=firestore" \
  --quiet

URL="$(gcloud run services describe "${SERVICE}" \
  --project="${PROJECT}" --region="${REGION}" --format='value(status.url)')"
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
