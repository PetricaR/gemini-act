# ADK dev web UI on Cloud Run

Deploys `adk web` — the UI you get from `make dev` — as its own IAP-locked Cloud Run
service, running the same agent as the Chat webhook.

**It is a second service.** It does not touch the `gemini-act` service, which keeps its
own URL; that URL is both its Chat JWT audience and its OAuth redirect base, so it
cannot be shared.

## Run it

```bash
make deploy-adk-ui          # or ./deploy/adk_ui/deploy_cloud_run.sh
```

Reads the same `.env` as the other deploy scripts. Overridable via env:
`ADK_UI_SERVICE`, `ADK_UI_BUCKET`, `IAP_USER`, `CLOUD_RUN_REGION`.

## What you get, and what you don't

| | |
| --- | --- |
| Agent | Anonymous mode — `build_agent(token_service=None)`, same as `make dev` |
| Tools | Business, Chat actions, Maps, imobiliare, search |
| Tools **not** present | Gmail / Drive / Calendar |
| Sessions | In memory, lost on revision replace |
| Artifacts | `gs://gemini-act-rapoarte-<project-number>/` |
| PDF reports | `gs://gemini-act-rapoarte-<project-number>/rapoarte/` |

Workspace tools are absent by construction, not by configuration: they are per-user
OAuth toolsets, and here there is no Chat user to resolve a token for. If you need to
exercise Gmail/Drive/Calendar, that only happens through the real Chat webhook.

## Access

IAP, configured directly on the service — no load balancer. The `run.app` URL demands a
Google sign-in before any request reaches the container, and only principals holding
`roles/iap.httpsResourceAccessor` pass. The script grants it to `IAP_USER` alone.

This matters more than usual: the ADK dev UI has no authentication of its own, and ADK's
own help calls it development-only. Anyone who could open the URL could run the agent on
this project's Vertex quota and Maps key. Do not swap `--iap` for
`--allow-unauthenticated`.

Adding someone later:

```bash
gcloud iap web add-iam-policy-binding --resource-type=cloud-run \
  --service=gemini-act-adk-ui --region=europe-west1 --project=website-formare-ai \
  --member=user:THEIR_EMAIL --role=roles/iap.httpsResourceAccessor
```

## PDF reports go to the bucket

`paths.reports_dir()` honours `IMOBILIARE_REPORTS_DIR`, which the deploy points at
`/mnt/gcs/rapoarte` — a bucket mounted through gcsfuse. A finished report is therefore
an object in the bucket, not a file on a container filesystem that disappears with the
instance.

The *cache* (`IMOBILIARE_CACHE_DIR`) stays on local `/tmp` on purpose: it is dozens of
listing photos per valuation, and pushing those through FUSE would be slow to no
purpose. Only the finished PDF crosses to GCS.

List them:

```bash
gcloud storage ls gs://gemini-act-rapoarte-428056592625/rapoarte/
```

## How hard it hits imobiliare.ro

The portal answers an over-eager client with an anti-bot interstitial —
*"Am detectat o anomalie în comportamentul browserului dumneavoastră"* — served as a
**200 with an HTML body**, which is why a naive client parses it as data and never
notices. `imobiliare_mcp/throttle.py` handles all three parts of that: it de-duplicates
(one listing is fetched once per run however many tools ask for it), paces what is left
per host, and detects the interstitial in order to stop.

This service sets a slightly slower pace than the local default —
`IMOBILIARE_MIN_INTERVAL=1.5`, `IMOBILIARE_MAX_PARALLEL=2` — because Cloud Run egresses
from a shared Google address pool rather than from an office IP, so the address it
appears as is one it does not control and may not arrive with a clean reputation. Turn
the interval up if blocks recur:

```bash
gcloud run services update gemini-act-adk-ui --region=europe-west1 \
  --project=website-formare-ai --update-env-vars=IMOBILIARE_MIN_INTERVAL=3
```

## Live (bidi) streaming

The UI's live mode is one long-lived WebSocket, so the service runs with
`--timeout=3600` (Cloud Run's maximum) and `min=max=1`, which also removes any need for
session affinity. Live mode additionally requires a model that serves the Live API — if
the toggle errors out, that is the model, not the deploy; set `GEMINI_ACT_MODEL` on this
service to a Live-capable model and redeploy.

## Cost

`min-instances=1` at 8Gi/4cpu with CPU always allocated is an always-on bill. It is not
tuning: sessions are in memory, so scaling to zero drops the conversation you are in.
Delete the service when you are not using it:

```bash
gcloud run services delete gemini-act-adk-ui --region=europe-west1 --project=website-formare-ai
```
