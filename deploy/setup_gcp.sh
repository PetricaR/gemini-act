#!/usr/bin/env bash
# One-time Google Cloud setup for Gemini Act.
#
# Idempotent: safe to re-run. What it cannot do is the console-only work —
# the OAuth consent screen, the OAuth web client, and the Google Chat API
# configuration page. See README.md for those.
set -euo pipefail

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
  firestore.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iamcredentials.googleapis.com \
  gmail.googleapis.com \
  drive.googleapis.com \
  docs.googleapis.com \
  calendar-json.googleapis.com \
  people.googleapis.com

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
  2. Deploy:  ./deploy/deploy_cloud_run.sh
  3. Grant Google Chat permission to invoke the service (deploy script does this).
  4. Google Chat API configuration page: set the HTTP endpoint URL to the
     Cloud Run URL and register the slash commands.
EOF
