#!/usr/bin/env bash
# Grant, revoke or list access to the IAP-locked ADK web UI.
#
# Usage:
#   ./grant_access.sh ana@example.com bogdan@example.com   # grant
#   ./grant_access.sh --revoke ana@example.com             # take it back
#   ./grant_access.sh --list                               # who has access now
#   ./grant_access.sh --service=gemini-act-adk-ui ...      # a different service
#
# A bare address is read as an individual Google account. To grant a whole
# group or domain, say so explicitly:
#
#   ./grant_access.sh group:proiect-imobiliare@formare.ai
#   ./grant_access.sh domain:formare.ai
#
# The explicitness is deliberate: `domain:formare.ai` opens the UI to everyone
# with an address at that domain, and that is too large a blast radius to reach
# by typo. What it opens is not a read-only page — whoever gets in can run the
# agent, spending this project's Vertex quota and using its Maps key, and can
# see every listing, report and conversation in the session list.
#
# Two things this does NOT do, both on purpose:
#
#   * It does not grant roles/run.invoker. IAP terminates the request and calls
#     the service as its own service agent, so the invoker role belongs to that
#     agent, not to the person. Granting it to a human would be a second, IAP-
#     free way in, which defeats the point.
#   * It does not touch the `gemini-act` Chat webhook service, which is a
#     different service with a different access model.
#
# The account must be a Google account (a Workspace address, or a personal one
# registered with Google). An address that cannot sign in to Google cannot pass
# IAP, and the failure looks like a sign-in loop rather than a clear error.
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
SERVICE="${ADK_UI_SERVICE:-gemini-act-adk-ui}"
ROLE="roles/iap.httpsResourceAccessor"

ACTION="grant"
MEMBERS=()

for arg in "$@"; do
  case "${arg}" in
    --revoke|--remove) ACTION="revoke" ;;
    --list|--show)     ACTION="list" ;;
    --service=*)       SERVICE="${arg#*=}" ;;
    --region=*)        REGION="${arg#*=}" ;;
    --project=*)       PROJECT="${arg#*=}" ;;
    -h|--help)
      sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    -*)
      echo "Unknown option: ${arg}" >&2
      exit 2
      ;;
    *)                 MEMBERS+=("${arg}") ;;
  esac
done

iap() {
  gcloud iap web "$@" \
    --resource-type=cloud-run \
    --service="${SERVICE}" \
    --region="${REGION}" \
    --project="${PROJECT}"
}

if [[ "${ACTION}" == "list" ]]; then
  echo "==> Who can open ${SERVICE} (${REGION}, ${PROJECT})"
  # get-iam-policy returns the whole policy; the accessor role is the one that
  # decides who gets past IAP. An empty result means nobody but project-level
  # admins, which is what a freshly deployed service looks like.
  iap get-iam-policy --format='value(bindings)' 2>/dev/null \
    | tr ';' '\n' | grep -i "httpsResourceAccessor" -A20 \
    || echo "    (no one — or you lack permission to read the policy)"
  exit 0
fi

if [[ ${#MEMBERS[@]} -eq 0 ]]; then
  echo "No addresses given. Try: $(basename "${BASH_SOURCE[0]}") ana@example.com" >&2
  echo "                   or: $(basename "${BASH_SOURCE[0]}") --list" >&2
  exit 2
fi

# Turn each argument into a fully-qualified IAM member.
normalise() {
  local raw="$1"
  case "${raw}" in
    user:*|group:*|domain:*|serviceAccount:*)
      echo "${raw}"
      ;;
    *@*)
      echo "user:${raw}"
      ;;
    *)
      echo "Refusing '${raw}': it has no '@' and no prefix." >&2
      echo "If you meant an entire domain, say so: domain:${raw}" >&2
      return 1
      ;;
  esac
}

echo "==> ${ACTION} on ${SERVICE} (${REGION}, ${PROJECT})"
for raw in "${MEMBERS[@]}"; do
  member="$(normalise "${raw}")"
  if [[ "${ACTION}" == "grant" ]]; then
    iap add-iam-policy-binding --member="${member}" --role="${ROLE}" >/dev/null
    echo "    + ${member}"
  else
    iap remove-iam-policy-binding --member="${member}" --role="${ROLE}" >/dev/null
    echo "    - ${member}"
  fi
done

URL="https://${SERVICE}-$(gcloud projects describe "${PROJECT}" \
  --format='value(projectNumber)').${REGION}.run.app"

cat <<EOF

Done. IAP policy changes can take a minute or two to take effect; until then a
just-granted account may still see a 403.

  ${URL}

Send that link. The first visit asks for a Google sign-in.
EOF
