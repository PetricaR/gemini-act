#!/usr/bin/env bash
# One-time Google Cloud setup for Gemini Act.
#
# Idempotent: safe to re-run. What it cannot do is the console-only work —
# the OAuth consent screen, the OAuth web client, and the Google Chat API
# configuration page. See README.md for those.
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
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${SERVICE_NAME:-gemini-act}"
SA="${SERVICE_ACCOUNT_NAME:-gemini-act-runtime}"
SA_EMAIL="${SA}@${PROJECT}.iam.gserviceaccount.com"

echo "==> Project ${PROJECT} / region ${REGION}"
gcloud config set project "${PROJECT}" >/dev/null

echo "==> Enabling APIs"
gcloud services enable \
  chat.googleapis.com \
  aiplatform.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iamcredentials.googleapis.com \
  gmail.googleapis.com \
  drive.googleapis.com \
  docs.googleapis.com \
  calendar-json.googleapis.com \
  people.googleapis.com \
  agentregistry.googleapis.com

# Workspace MCP servers (Gmail, Drive, Calendar, Chat, People) are resolved via
# Cloud Agent Registry (agentregistry.googleapis.com, enabled above) rather than
# called directly at their public https://*mcp.googleapis.com/mcp/v1 URLs. Those
# direct URLs belong to the Workspace MCP Developer Preview Program, which is
# allowlist-gated per project (https://developers.google.com/workspace/preview);
# Agent Registry exposes the same first-party servers without that enrollment.
# See `config.MCP_SERVERS` for exactly which servers this app expects to find
# registered — confirm they show up for this project in the Agent Registry
# console before deploying.

echo "==> Firestore database (native mode)"
if ! gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
  gcloud firestore databases create --location="${REGION}" --type=firestore-native
else
  echo "    already exists"
fi

echo "==> Runtime service account ${SA_EMAIL}"
if ! gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA}" --display-name="Gemini Act runtime"
else
  echo "    already exists"
fi

echo "==> IAM roles"
for ROLE in roles/aiplatform.user roles/datastore.user roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --condition=None >/dev/null
  echo "    ${ROLE}"
done

cat <<EOF

==> Setup complete.

Service account: ${SA_EMAIL}

Still to do by hand (see README.md):
  1. OAuth consent screen + Web client, redirect URI:
       https://<your-cloud-run-url>/oauth/callback
  2. Confirm the servers in config.MCP_SERVERS (gmailmcp, drivemcp, calendarmcp,
     chatmcp, people) show up under Agent Registry for this project, and that
     ${SA_EMAIL} has read access to them — the runtime service account calls
     agentregistry.googleapis.com with its own identity to resolve each
     server's endpoint. There is no single documented IAM role for this yet;
     grant whatever the console's "Agent Registry" section asks for a caller
     that only needs to read/use registered servers.
  3. Deploy:  ./deploy/deploy_cloud_run.sh
  4. Grant Google Chat permission to invoke the service (deploy script does this).
  5. Google Chat API configuration page: set the HTTP endpoint URL to the
     Cloud Run URL and register the slash commands.
EOF
