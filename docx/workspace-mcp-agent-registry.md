# Workspace MCP via Cloud Agent Registry

Status: **working in production** (`website-formare-ai`, `gemini-act` on Cloud Run, `europe-west1`).

This documents what was actually broken, why, and the exact fix — written after several rounds of
trial and error so the next person (or the next redeploy) doesn't repeat them.

## The problem

Gemini Act calls Google's first-party Workspace MCP servers (Gmail, Drive, Calendar, Chat, People)
so the agent can act on a Chat user's behalf. These servers have public URLs
(`https://gmailmcp.googleapis.com/mcp/v1`, etc.) documented at
<https://developers.google.com/workspace/guides/configure-mcp-servers>.

Calling those URLs directly returned **403 on every request**, regardless of OAuth setup. Reason:
they belong to the **Workspace MCP Developer Preview Program**
(<https://developers.google.com/workspace/preview>), which is allowlist-gated per GCP project. The
`website-formare-ai` project is not enrolled.

## The fix: Cloud Agent Registry

Google exposes the *same* first-party servers through **Cloud Agent Registry**
(`agentregistry.googleapis.com`), under a different, non-allowlisted entitlement. Instead of a
static public URL, each server is a *resource* in Agent Registry:

```text
projects/{project}/locations/{location}/mcpServers/{id}
```

`google.adk.integrations.agent_registry.AgentRegistry.get_mcp_toolset(resource_name)` resolves that
resource into a ready-to-use `McpToolset`. This is what `build_workspace_toolsets()` in
[`src/gemini_act/agent/tools/workspace_mcp.py`](../src/gemini_act/agent/tools/workspace_mcp.py) now
does, for every server in `Settings.mcp_enabled`.

## The gotchas (in the order they actually bit us)

Each of these produced a distinct, confusing failure. Recorded so nobody re-diagnoses them from
scratch.

### 1. `location` must be `global`, not a region

**Symptom:** `404 Not Found` — resource genuinely doesn't exist at the requested path.

Vertex AI serves `gemini-3.6-flash` only from the `global` endpoint (regional locations 404). Agent
Registry's MCP servers for this project are *also* registered under `global`. `.env` had
`GOOGLE_CLOUD_LOCATION=us-central1` (copied from an old example), which fed into both the model
config and the Agent Registry resource path — wrong for both, for the same reason.

**Fix:** `GOOGLE_CLOUD_LOCATION=global` everywhere (`.env`, `.env.example`,
`deploy/deploy_cloud_run.sh` default).

### 2. The runtime service account needs Agent Registry read access — `roles/agentregistry.viewer`

**Symptom:** `403 Forbidden`, `agentregistry.googleapis.com` responds with `PERMISSION_DENIED`.

`AgentRegistry.get_mcp_toolset()` calls `agentregistry.googleapis.com` using the *service's own*
identity (ADC — the Cloud Run runtime service account), not the end user's token. That identity
had no permission to read Agent Registry resources at all.

**Diagnosis** (there is no single documented IAM role for this preview API, so this had to be
found empirically):

```bash
TOKEN=$(gcloud auth print-access-token --impersonate-service-account=gemini-act-runtime@website-formare-ai.iam.gserviceaccount.com)
curl -s -H "Authorization: Bearer ${TOKEN}" \
  "https://agentregistry.googleapis.com/v1/projects/website-formare-ai/locations/global/mcpServers/gmailmcp"
```

The response's `error.details[].metadata.permission` gave the exact missing permission:
**`agentregistry.mcpServers.get`**.

It was granted through the Console UI first (`roles:queryGrantableRoles` doesn't yet recognize
this resource type well enough to script the lookup), then confirmed and captured back afterward by
reading the project's actual IAM policy:

```bash
curl -s -X POST -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://cloudresourcemanager.googleapis.com/v1/projects/website-formare-ai:getIamPolicy" \
  | python3 -c "
import json, sys
for b in json.load(sys.stdin)['bindings']:
    if any('gemini-act-runtime' in m for m in b['members']):
        print(b['role'])
"
```

**Fix:** `roles/agentregistry.viewer` on `gemini-act-runtime@website-formare-ai.iam.gserviceaccount.com`
— now scripted in `deploy/setup_gcp.sh`'s IAM roles loop, no longer a manual step.

### 3. The registered resource **id** is not a slug — it's an opaque, auto-generated string

**Symptom:** `400 Bad Request` for `mcpServers/gmailmcp.googleapis.com` (a `.` is not a legal
character in that path segment); `404 Not Found` for `mcpServers/gmailmcp` (valid syntax, wrong
resource — no server is actually registered under that short id).

The Console's "Name" column (`gmailmcp.googleapis.com`) and the truncated "MCP Server ID" column
are both **display** values, not the resource id. The real id looks like
`agentregistry-00000000-0000-0000-694e-6cd3d0570769` — generated once when Google auto-provisioned
these first-party entries for this project, with no relationship to the server's product name.

**Discovery** (list and match on `displayName`):

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://agentregistry.googleapis.com/v1/projects/website-formare-ai/locations/global/mcpServers?pageSize=100" \
  | python3 -c "
import json, sys
for s in json.load(sys.stdin)['mcpServers']:
    print(s['name'], '|', s['displayName'])
"
```

**Fix:** hardcoded the discovered ids in
[`src/gemini_act/config.py`](../src/gemini_act/config.py) (`MCP_SERVERS`), since they are stable
once provisioned but not predictable or portable to another project. If this is ever pointed at a
different GCP project, **re-run the listing above** and update the table.

Current mapping (`website-formare-ai`, provisioned 2026-08-07):

| `mcp_enabled` key | Resource id | Display name |
| --- | --- | --- |
| `gmail` | `agentregistry-00000000-0000-0000-694e-6cd3d0570769` | `gmailmcp.googleapis.com` |
| `drive` | `agentregistry-00000000-0000-0000-1ac8-248c78d4ed27` | `drivemcp.googleapis.com` |
| `calendar` | `agentregistry-00000000-0000-0000-16d6-cee169897afc` | `calendarmcp.googleapis.com` |
| `chat` | `agentregistry-00000000-0000-0000-263a-52b590fe274c` | `chatmcp.googleapis.com` |
| `people` | `agentregistry-00000000-0000-0000-30c9-08a2641d3196` | `people.googleapis.com` |

Not registered for this project (and therefore not usable): Docs, Sheets, Slides, the universal
"workspace" search server. Registered but intentionally not wired in (infra/ops, not relevant to a
Chat business-user assistant): BigQuery, Compute, Cloud Run, Storage, Monitoring, Logging,
Dataplex, Pub/Sub, Cloud Trace, Cloud Resource Manager, Vertex AI, AppTopology, SaaS Service Mgmt,
Agent Registry itself, Maps.

### 4. `AgentRegistry`'s built-in header provider can't be async

`get_mcp_toolset()` wires up its own `combined_header_provider`, a **synchronous** closure that
does `headers.update(self._header_provider(ctx))` with no `await`. This app's per-user token
lookup (`TokenService.get_access_token`) is async (Firestore/HTTP). Routed through
`AgentRegistry`'s constructor, that hands `.update()` an un-awaited coroutine object and breaks
silently/confusingly.

**Fix:** don't pass `header_provider` to `AgentRegistry(...)` at all. Instead, set our own async
provider directly on the returned toolset (`toolset._header_provider = ...`) —
`McpToolset._execute_with_session` *does* correctly `await` an awaitable provider when called that
way. See the comment in `workspace_mcp.py:82-88`.

### 5. `AgentRegistry`'s connection timeout can't be configured

`get_mcp_toolset()` always builds `StreamableHTTPConnectionParams` with ADK's default 5s timeout
and exposes no parameter to change it. These servers routinely take 15-25s for `tools/list`
(observed), so every toolset silently timed out and the agent lost its Workspace tools.

**Fix:** mutate `toolset._connection_params.timeout = settings.mcp_timeout_seconds` (90s) after
construction — the value is read fresh on every call, not cached at construction time, so this
works. See `workspace_mcp.py:89-92`.

### 6. `AgentRegistry` requires extra, non-default `google-adk` extras

Importing `google.adk.integrations.agent_registry` transitively requires the `a2a` extra
(`a2a-sdk`) and the `agent-identity` extra (`google-cloud-agentidentitycredentials`,
`google-cloud-iamconnectorcredentials`) — neither is pulled in by the `gcp`/`mcp` extras this repo
already depended on.

**Fix:** `pyproject.toml` now installs `google-adk[gcp,mcp,a2a,agent-identity]`.

### 7. `deploy_cloud_run.sh --source=.` breaks if run from `deploy/`

**Symptom:** Cloud Build fails detection for every language buildpack (Go, Java, Python, Node,
Ruby, PHP all report "no source files found").

`--source=.` uses the shell's current directory. Running `bash deploy_cloud_run.sh` from inside
`deploy/` (natural, since that's where the script lives) uploaded the `deploy/` folder itself —
no `pyproject.toml`, no `.py` files — as the build source.

**Fix:** `--source="${REPO_ROOT}"`, where `REPO_ROOT` is computed from the script's own path, so it
no longer matters which directory the script is invoked from.

### 8. Deploy/setup scripts didn't read `.env`

Both scripts required every variable to be exported manually in the shell first. Added, at the top
of both `deploy/deploy_cloud_run.sh` and `deploy/setup_gcp.sh`:

```bash
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  source "${REPO_ROOT}/.env"
  set +a
fi
```

`.env` values win over anything already exported — same as running `source .env` by hand. Note:
`.env` is parsed as literal `KEY=value` by both this bash loader and by the app's own
`pydantic-settings` loader — **no shell command substitution** (`$(...)`) is executed by either;
a value like `$(openssl rand -hex 32)` is stored as that literal string, not the command's output.
Generate secrets separately and paste the resulting value in.

## Current architecture

```text
Settings.mcp_enabled (config.py)
        │
        ▼
build_workspace_toolsets(settings, token_service)      [workspace_mcp.py]
        │
        │  for each enabled server:
        │    resource_name = projects/{project}/locations/{location}/mcpServers/{MCP_SERVERS[server]}
        │    toolset = AgentRegistry(...).get_mcp_toolset(resource_name)
        │    toolset._header_provider = <our async per-user token provider>
        │    toolset._connection_params.timeout = settings.mcp_timeout_seconds
        │    toolset.tool_name_prefix = server
        ▼
CachingToolset(toolset, cache_ttl_seconds=...)          [caching_toolset.py]
        │  (wraps by composition, not inheritance — works with whatever
        │   AgentRegistry.get_mcp_toolset() returns)
        ▼
Agent.tools                                              [factory.py]
```

`token_service is None` (the `adk web` / anonymous case —
[`agents/chat_agent/agent.py`](../agents/chat_agent/agent.py)) short-circuits to an empty list:
**all** Workspace toolsets are skipped, not just one, because none of them can act without a real
Chat user's OAuth token. This is expected, not a bug — it's how local `adk web` testing is meant to
work; only Chat tools and business tools are available there.

## Verifying it works

Without deploying, authenticating as yourself (ADC) instead of a Chat user:

```bash
.venv/bin/python scripts/check_workspace_mcp.py
```

This resolves the same toolsets `build_workspace_toolsets` builds for a real user and calls
`get_tools()` on each — confirms Agent Registry resolution and a live `tools/list` round trip
independent of the Chat OAuth flow. A 403 from a *specific* server after this succeeds points at
OAuth scope/consent for that server, not at Agent Registry.

Cloud Run logs, if something breaks again:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" resource.labels.service_name="gemini-act" severity>=ERROR' \
  --project=website-formare-ai --limit=5 --format=json --freshness=15m
```

## Files touched by this fix

- `src/gemini_act/config.py` — `MCP_SERVERS` (resource ids), `MCP_SCOPES` (trimmed to
  gmail/drive/calendar/chat/people), default `mcp_enabled`.
- `src/gemini_act/agent/tools/workspace_mcp.py` — rebuilt on `AgentRegistry.get_mcp_toolset()`.
- `src/gemini_act/agent/tools/caching_toolset.py` — `CachingMcpToolset` (subclass of `McpToolset`)
  → `CachingToolset` (composition wrapper of any `BaseToolset`).
- `pyproject.toml` / `uv.lock` — added `a2a`, `agent-identity` extras.
- `deploy/setup_gcp.sh` — enables `agentregistry.googleapis.com`; drops the old per-product
  Developer Preview service list; loads `.env`; grants `roles/agentregistry.viewer` to the
  runtime service account.
- `deploy/deploy_cloud_run.sh` — `--source="${REPO_ROOT}"`; `.env` loading; default
  `mcp_enabled`/`location` fixed.
- `.env`, `.env.example` — `GOOGLE_CLOUD_LOCATION=global`; `GEMINI_ACT_MCP_ENABLED` without `docs`.
- `scripts/check_workspace_mcp.py` — new, local smoke test (see above).
- `tests/test_agent.py`, `tests/test_caching_toolset.py` — updated for the above; a
  `FakeAgentRegistry` stands in for the real one so tests don't need ADC or network.

## Known gaps

- `MCP_SERVERS` ids are hardcoded for `website-formare-ai`. Moving to a different GCP project means
  re-running the discovery `curl` in gotcha #3 and updating the table by hand — there's no dynamic
  lookup-by-`displayName` at runtime (a reasonable follow-up if this needs to become
  project-portable).
