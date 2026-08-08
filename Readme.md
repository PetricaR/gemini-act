# Gemini Act

A [Google ADK](https://adk.dev) agent that takes real actions from inside Google Chat.

You DM the app or @-mention it in a space; it reasons, calls tools — your mail, calendar, Drive,
Chat, internal APIs — and answers in the conversation. Same idea as [OpenClaw](https://github.com/openclaw/openclaw)
(an agent runtime bridged into a messaging platform), rebuilt on Google's stack and scoped to
Google Workspace rather than shell access.

## How it works

```text
Chat message
   │  HTTPS POST, bearer token issued by chat@system.gserviceaccount.com
   ▼
Cloud Run — FastAPI
   ├─ verify the bearer token ──────────── fails → 401
   ├─ route the event (MESSAGE / APP_COMMAND / ADDED_TO_SPACE)
   ├─ no credentials for this user? → auth card, stop
   ├─ 200 immediately (empty body)
   └─ background: run the agent, post the answer via the Chat API
```

Three design points worth knowing before you change anything:

**The reply is asynchronous.** Chat allows roughly 30 seconds for a synchronous response, which an
agent loop with tool calls routinely exceeds. So the webhook acknowledges immediately and the real
answer is posted afterwards with `spaces.messages.create`.

**Workspace MCP servers are per-user OAuth, not service-account.** A Chat event tells us *who* is
asking but carries no token for them, so the app runs its own consent flow and keeps refresh tokens
in Firestore keyed by Chat user id.

**One agent instance serves everyone.** `McpToolset` takes a `header_provider` callback that runs
per invocation and receives the user id, so the caller's token is resolved at tool-call time. ADK
pools MCP sessions by a hash of the resolved headers, so users never share an upstream session.
This is why there is no per-request agent construction. The same property is what lets users add
their own MCP servers at runtime — see below.

## Layout

| Path | What lives there |
| --- | --- |
| [src/gemini_act/config.py](src/gemini_act/config.py) | Settings, MCP endpoints, OAuth scopes |
| [src/gemini_act/agent/factory.py](src/gemini_act/agent/factory.py) | Agent assembly |
| [src/gemini_act/agent/tools/](src/gemini_act/agent/tools/) | Workspace MCP, user MCP, Chat actions, business tools |
| [src/gemini_act/chat/](src/gemini_act/chat/) | Webhook, request verification, cards, Chat API client |
| [src/gemini_act/mcp/](src/gemini_act/mcp/) | Parsing and storage of user-connected MCP servers |
| [src/gemini_act/oauth/](src/gemini_act/oauth/) | Consent flow and per-user token store |
| [src/gemini_act/runner.py](src/gemini_act/runner.py) | ADK Runner and session wiring |
| [agents/chat_agent/](agents/chat_agent/) | `adk web` entry point (anonymous mode) |

## Connecting your own MCP servers

Paste a server into the chat and it is connected for you — no redeploy, no config change, and
nobody else's agent is affected:

```text
https://mcp.example.com/mcp
```

A JSON config works too, including the block a vendor gives you for Claude Desktop or VS Code,
fenced or not, with several servers in it:

```json
{"mcpServers": {"acme": {"url": "https://acme.example.com/mcp",
                         "headers": {"Authorization": "Bearer sk-..."}}}}
```

Its tools appear on your next message, prefixed with the server's name (`acme_search`), and
`/mcp` lists what you have connected while `/mcp remove <name>` disconnects one.

How it works: [`CustomMcpToolset`](src/gemini_act/agent/tools/custom_mcp.py) resolves the *calling*
user's servers inside `get_tools()`, which ADK invokes per LLM turn with the user id attached —
so one shared agent serves everyone's different tool lists. A pasted server is connected for real
and asked for its tools before it is saved, so a wrong URL or a bad token fails once, visibly,
instead of on every later turn.

Three limits are deliberate:

- **Remote servers only.** A stdio config (`"command": "npx"`) is refused rather than run: it would
  mean executing a command chosen by a chat message inside the agent's container.
- **https only**, localhost excepted, since a config's headers usually hold a token.
- **Per user.** Servers are stored under the Chat user id and never shared between people.

Read [`GEMINI_ACT_CUSTOM_MCP_ALLOWED_HOSTS`](.env.example) before enabling this for a wide
audience. The default accepts any https host, and a pasted server's tools run in the same agent
turn as that user's Workspace tools — so a hostile server can see what the agent has fetched and
can return text that tries to steer it. The agent is instructed to treat those results as data,
never as instructions, but an allowlist is the control that does not depend on the model.
`GOOGLE_API_USE_CLIENT_CERTIFICATE=false` matters here too, for a different reason spelled out in
[custom_mcp.py](src/gemini_act/agent/tools/custom_mcp.py).

## Quick start

```bash
uv sync
cp .env.example .env      # then fill it in
make dev                  # ADK dev UI at localhost:8000
```

`make dev` runs the agent **anonymously** — no Chat user means no Workspace access token, so the
MCP toolsets are left out by design. Business and Chat tools work. It's the right loop for
iterating on prompts and tool schemas.

## Google Cloud setup

### 0. Prerequisites

- A **Google Workspace** account (Business or Enterprise). Google Chat apps cannot be configured
  from a personal Google account.
- A Google Cloud project with **billing enabled**.
- Enrolment in the [Google Workspace Developer Preview Program](https://developers.google.com/workspace/preview).
  The Workspace **MCP servers are Developer Preview, not GA** — without enrolment the
  `*mcp.googleapis.com` services cannot be enabled and every Workspace toolset will fail at
  runtime. Everything else (Chat webhook, agent, business tools) works without it: set
  `GEMINI_ACT_MCP_ENABLED=` empty to run in that mode.

You do **not** need a Marketplace listing or a domain-wide allowlist to test: an unpublished Chat
app can be used by up to
[5 users](https://support.google.com/a/answer/7651360) while in development.

### 1. Scripted

```bash
export GOOGLE_CLOUD_PROJECT=your-project
export GOOGLE_CLOUD_LOCATION=us-central1
./deploy/setup_gcp.sh
```

Enables the APIs, creates the Firestore database, and creates the runtime service account with
`aiplatform.user`, `datastore.user` and `logging.logWriter`.

### 2. OAuth consent screen and client (console only)

In **Google Auth Platform → Branding**, configure the app name, support email, audience
(**Internal** for a Workspace domain) and contact email.

Under **Data Access → Add or Remove Scopes**, add the scopes for the servers you enable. These must
match [`MCP_SCOPES`](src/gemini_act/config.py) or authorization fails at runtime:

| Server | Scopes |
| --- | --- |
| Gmail | `gmail.readonly`, `gmail.compose` |
| Drive | `drive.readonly`, `drive.file` |
| Docs | `drive.readonly`, `drive.file`, `documents` |
| Calendar | `calendar.calendarlist.readonly`, `calendar.events.freebusy`, `calendar.events` |
| Chat | `chat.spaces.readonly`, `chat.memberships.readonly`, `chat.messages.readonly`, `chat.messages.create` |
| People | `directory.readonly`, `contacts.readonly` |
| BigQuery | `bigquery` |
| Maps | `maps-platform.mapstools` |
| Storage | `devstorage.read_write` |

Maps is the easy one to miss: without `maps-platform.mapstools` the toolset still *starts* cleanly
(discovery logs "Discovered 5 maps tool(s)") and only the first actual tool call fails, as a
`403 Forbidden` that ADK reports as a lost MCP session rather than as a consent problem.

Adding a scope here is not enough on its own — tokens already stored for a user were issued against
the old scope set and keep working with it, so anyone who authorized before the change has to
re-authorize before the new server works for them.

Then **Clients → Create Client → Web application**. Authorized redirect URI:

```text
https://<your-cloud-run-url>/oauth/callback
```

Copy the client ID and secret into your environment.

### 3. Deploy

```bash
export GEMINI_ACT_OAUTH_CLIENT_ID=...
export GEMINI_ACT_OAUTH_CLIENT_SECRET=...
export GEMINI_ACT_STATE_SECRET=$(openssl rand -hex 32)
./deploy/deploy_cloud_run.sh
```

The script deploys twice on purpose: the service's own URL is both the OAuth redirect base and the
JWT audience Chat signs against, so it deploys once to learn the URL and then applies it. It also
grants `chat@system.gserviceaccount.com` the Cloud Run invoker role.

### 4. Google Chat API configuration (console only)

**Google Cloud console → Google Chat API → Configuration**:

- **App name**: Gemini Act
- **Functionality**: receive 1:1 messages, join spaces and group conversations
- **Connection settings**: HTTP endpoint URL → your Cloud Run URL
- **Visibility**: your domain or a test group

Register the slash commands, whose ids must match
[`SLASH_COMMANDS`](src/gemini_act/chat/events.py):

| ID | Command | Description |
| --- | --- | --- |
| 1 | `/help` | Show what I can do |
| 2 | `/auth` | Connect your Google account |
| 3 | `/reset` | Forget this thread's conversation |
| 4 | `/whoami` | Show which account I'm using |
| 5 | `/clean` | Delete every message in this conversation |
| 6 | `/mcp` | List, add or remove your MCP servers |

> Your Workspace admin may need to allowlist the app before it is installable. Worth checking
> early — it blocks all end-to-end testing.

## Local end-to-end testing

Google Chat can only reach a public HTTPS URL, so tunnel:

```bash
make serve            # terminal 1
make tunnel           # terminal 2 — prints a public https URL
```

Put that URL in both `GEMINI_ACT_CHAT_AUDIENCE` and `GEMINI_ACT_PUBLIC_BASE_URL`, set it as the
HTTP endpoint URL on the Chat API page, add `<url>/oauth/callback` to the OAuth client, and restart
`make serve`.

`GEMINI_ACT_VERIFY_CHAT_REQUESTS=FALSE` skips request verification for local poking with `curl`.
Never deploy that way — it leaves the endpoint open to anyone who finds it.

## Configuration

Everything is environment-driven; see [.env.example](.env.example). The ones that matter most:

| Variable | Notes |
| --- | --- |
| `GEMINI_ACT_CHAT_AUDIENCE` | Must exactly equal the HTTP endpoint URL on the Chat API page — it is the JWT audience |
| `GEMINI_ACT_PUBLIC_BASE_URL` | Base for the OAuth redirect URI |
| `GEMINI_ACT_STATE_SECRET` | Signs the OAuth `state`; a weak value lets someone bind their Google account to another Chat user |
| `GEMINI_ACT_MCP_ENABLED` | Which Workspace MCP servers to expose |
| `GEMINI_ACT_SESSION_DB_URL` | Empty means in-memory sessions, lost on restart |

## Adding tools

Business actions go in [business.py](src/gemini_act/agent/tools/business.py). ADK derives each
tool's schema from the signature, type hints and docstring, so all three are load-bearing:

```python
def check_stock(sku: str, store_code: str) -> dict[str, Any]:
    """Check stock for a product at a store.

    Args:
        sku: Product identifier, e.g. "SKU-001".
        store_code: Store code, e.g. "1234".

    Returns:
        A dict with "status", and on success "quantity"; on error an "error_message".
    """
```

Always return a dict with a `status` key — the system prompt tells the agent to trust it to
distinguish success from failure, and to never report a failed action as successful.

The prompt also requires the agent to confirm before any tool call that writes, sends, shares or
deletes. If you add a destructive tool, keep that contract.

Shell and filesystem tools — the most OpenClaw-like capability — are deliberately **not** included.
If you add them, gate them behind an allowlist (there is a placeholder in `business.py`) and never
expose them in a shared space, where anyone who can post a message can invoke them.

## Development

```bash
make test     # pytest
make lint     # ruff
make fmt      # ruff format + autofix
```
