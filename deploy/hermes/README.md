# Hermes Agent on Cloud Run

Deploys [Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research, MIT)
as an IAM-locked Cloud Run service with a browser dashboard, using Gemini as its model.

**This is not gemini-act.** Hermes is a separate, self-hosted agent with its own model,
loop and memory. It does not run the ADK agent in `src/gemini_act/` — none of that
system prompt, the A2UI cards, the Chat streaming or the per-user Workspace OAuth is
involved. The intended link between the two is MCP: Hermes connects to the
`imobiliare-mcp` server in this repo and calls its tools, with Gemini driving the loop.

These files live here because this is where the project's deploy tooling already is.
They deploy a different service and never touch the `gemini-act` service.

## Files

| File | Purpose |
| --- | --- |
| `deploy_cloud_run.sh` | Creates the bucket, mirrors the image, deploys the service |
| `config.yaml` | Hermes config, seeded into the state bucket before first boot |

## Three constraints worth understanding before changing anything

**All state lives in one directory.** Config, `.env`, `memories/`, `skills/`,
`sessions/` and `state.db` all sit under `/opt/data`. Cloud Run has no attachable
disk, so that directory is a GCS bucket mounted via FUSE. Everything except
`state.db` is plain files and survives this fine.

**`state.db` needs `journal_mode: delete`.** It is SQLite, and WAL mode requires
mmap and POSIX locking that GCS FUSE does not provide. `config.yaml` pins `delete`,
which Hermes documents as the mode for network mounts. This is why the config is
uploaded *before* the first boot: Hermes picks a journal mode when it creates the
database and never live-downgrades an existing WAL database afterwards. Expect the
session database to feel slow — small random writes over FUSE are not fast.

**The service cannot scale to zero.** Hermes' docs: *"Never run two Hermes gateway
containers against the same data directory simultaneously."* Hence `min=max=1`,
hence always-on billing — roughly €40–60/month at 4Gi.

## Access

The dashboard embeds a live PTY — a real terminal inside the container, next to
shell tools and the mounted API keys. Access is therefore locked to a single
Google identity, in two layers.

**IAP, configured directly on the service** — no load balancer, which
[went GA](https://cloud.google.com/blog/products/serverless/iap-integration-with-cloud-run)
and replaced the old serverless-NEG setup. The `run.app` URL opens in a browser
and IAP demands a Google sign-in before any request reaches the container. Only
principals holding `roles/iap.httpsResourceAccessor` pass; the script grants it
to `IAP_USER` alone. Everyone else gets a 403 at the edge.

Note the inversion this creates: IAP terminates the request and then calls the
service as *itself*, so `roles/run.invoker` belongs to the IAP service agent,
not to you. The service stays `--no-allow-unauthenticated`, and `--ingress=all`
is required — IAP is the gate, not network reachability.

**Hermes' own basic auth** sits behind that. Hermes refuses a non-loopback bind
without an auth provider, so it is required regardless; treat it as defence in
depth rather than the real boundary.

To add someone later:

```bash
gcloud iap web add-iam-policy-binding --resource-type=cloud-run \
  --service=hermes --region=europe-west1 --project=website-formare-ai \
  --member=user:THEIR_EMAIL --role=roles/iap.httpsResourceAccessor
```

## Running it

Create the two secrets first — the script deliberately does not handle secret
material:

```bash
PROJECT=website-formare-ai

gcloud secrets create hermes-gemini-key --replication-policy=automatic --project=$PROJECT
grep '^GEMINI_API_KEY=' ../../.env | cut -d= -f2- \
  | gcloud secrets versions add hermes-gemini-key --data-file=- --project=$PROJECT

gcloud secrets create hermes-dash-pass --replication-policy=automatic --project=$PROJECT
openssl rand -base64 24 | tr -d '\n' \
  | gcloud secrets versions add hermes-dash-pass --data-file=- --project=$PROJECT

./deploy_cloud_run.sh
```

Overridable via env: `PROJECT`, `REGION`, `SERVICE`, `BUCKET`, `DASH_USER`, `UPSTREAM`.

## Status

**Unverified.** This script has been syntax-checked but never executed — the
deploying environment was not permitted to create GCP resources. Treat the first
run as a debugging session, not a deploy.

The riskiest assumption is that s6-overlay gets PID 1 under Cloud Run. The image
entrypoint checks for this; if it is not PID 1 it prints
`WARNING: container entrypoint is not PID 1` and falls back to a direct
bootstrap where **supervised services are unavailable** — meaning the dashboard
never starts and the service answers nothing on 9119. Grep the logs for that
warning first if the UI does not come up.

Verify after the first boot:

```bash
gcloud storage ls gs://hermes-data-428056592625/        # config.yaml, then state.db
gcloud run services logs read hermes --region=europe-west1 --project=website-formare-ai
```

Confirm `state.db` is not in WAL mode — no `state.db-wal` or `state.db-shm` files
should appear in the bucket. If they do, the seeded config did not apply and the
database needs an offline `PRAGMA journal_mode=DELETE` before it corrupts.
