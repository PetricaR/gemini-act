# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A [Google ADK](https://adk.dev) agent (Python, FastAPI on Cloud Run) that runs inside Google Chat:
users DM it or @-mention it in a space, it reasons, calls tools — Gmail, Drive, Calendar, Chat,
internal business APIs — and replies in the conversation.

## Commands

```bash
uv sync                 # install deps from uv.lock
make dev                # ADK dev UI at localhost:8000, runs the agent anonymously (no Chat user
                         # -> no Workspace OAuth token -> Workspace MCP toolsets excluded; business
                         # and Chat tools still work). Right loop for iterating on prompts/schemas.
make voice               # same dev UI, for talking to the agent out loud: pick `live_agent`,
                         # click the microphone (see "Voice" below)
make serve               # Chat webhook locally on :8080 (uvicorn --reload)
make tunnel               # cloudflared tunnel to :8080, for real Chat -> webhook E2E testing
make test                 # uv run pytest -q
make lint                 # uv run ruff check .
make fmt                  # uv run ruff format . && ruff check --fix .
make setup                # ./deploy/setup_gcp.sh — one-time GCP project setup
make deploy                # ./deploy/deploy.sh — deploys twice (see below)
```

Run a single test: `uv run pytest tests/test_events.py::test_name -q`. Tests live flat under
`tests/`, one file per `src/gemini_act/...` module; `tests/conftest.py` forces safe env defaults
(in-memory token store, verification off, dummy OAuth/state secrets) *before* `gemini_act` is
imported and disables `.env` loading, so the suite never depends on a developer's local `.env` or
real GCP credentials.

Lint/format config is in `pyproject.toml` (`ruff`, line-length 100, `select = ["E","F","I","UP","B"]`).

## Request flow

```text
Chat message
   │  HTTPS POST, bearer token issued by chat@system.gserviceaccount.com
   ▼
Cloud Run — FastAPI (chat/app.py)
   ├─ verify the bearer token ──────────── fails → 401  (chat/auth.py)
   ├─ route the event: MESSAGE / APP_COMMAND / ADDED_TO_SPACE  (chat/events.py)
   ├─ no credentials for this user? → auth card, stop
   ├─ 200 immediately (empty body)
   └─ background task: run the agent, post the answer via the Chat API
```

Three non-obvious things worth knowing before changing this:

- **Replies are asynchronous.** Chat's synchronous window is ~30s; an agent loop with tool calls
  routinely exceeds it. The webhook acks immediately and the real answer is posted afterwards with
  `spaces.messages.create` (`runner.py`, `chat/events.py`). `Settings.agent_timeout_seconds` (180s)
  is the budget for the background run, independent of Chat's own window.
- **Workspace MCP servers are per-user OAuth, not service-account.** A Chat event says *who* is
  asking but carries no token for them, so the app runs its own consent flow (`oauth/routes.py`)
  and keeps refresh tokens in Firestore keyed by Chat user id (`oauth/store.py`).
- **One `Agent` instance serves everyone** (`agent/factory.py:get_agent`, `lru_cache`d). Workspace
  `McpToolset`s take a `header_provider` callback that runs per invocation and resolves the calling
  user's token at tool-call time; ADK pools MCP sessions by a hash of the resolved headers, so users
  never share an upstream session and there is no per-request agent construction. The same mechanism
  is what lets users attach their own MCP servers at runtime (see below).

## Layout

| Path | What lives there |
| --- | --- |
| `src/gemini_act/config.py` | Settings (env-driven), MCP server ids, OAuth scopes per server |
| `src/gemini_act/agent/factory.py` | Agent assembly (`build_agent`, process-wide `get_agent`) |
| `src/gemini_act/agent/prompts.py` | System instruction |
| `src/gemini_act/agent/tools/` | Business tools, Chat action tools, Workspace MCP, user-added MCP, search |
| `src/gemini_act/chat/` | Webhook (`app.py`), request verification, event routing/commands (`events.py`), cards, streaming, Chat API client |
| `src/gemini_act/mcp/` | Parsing/storage of user-connected MCP servers |
| `src/gemini_act/oauth/` | Consent flow and per-user token store |
| `src/gemini_act/runner.py` | ADK `Runner` wiring: one agent turn, Chat text in → reply text out |
| `agents/chat_agent/` | `adk web` entry point (anonymous mode, used by `make dev`) |
| `agents/live_agent/` | Same agent on a Live model, for voice (`make voice`) |

## Adding tools

Business actions go in `agent/tools/business.py`. ADK derives each tool's schema from the function
signature, type hints, *and* docstring — all three are load-bearing, not just documentation:

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

Always return a dict with a `status` key — the system prompt tells the agent to trust it to tell
success from failure, never to report a failed action as successful. The prompt also requires the
agent to confirm before any tool call that writes, sends, shares or deletes; keep that contract for
new destructive tools. Shell/filesystem tools are deliberately not included — if you add any, gate
them behind an allowlist and never expose them in a shared space where anyone can post a message.

## Workspace MCP servers (`agent/tools/workspace_mcp.py`, `config.py`)

Resolved through Google's **Agent Registry** (`agentregistry.googleapis.com`), not called at their
public `*mcp.googleapis.com` URLs directly — the direct route requires Workspace MCP Developer
Preview enrollment, Agent Registry doesn't. `MCP_SERVERS` in `config.py` maps short names
(`gmail`, `drive`, ...) to opaque per-project registry ids that must be re-derived (via the Agent
Registry list API) if this is ever pointed at a different GCP project — the ids are not portable.

Adding or changing a server touches three places that must stay in sync: `MCP_SERVERS` (registry
id), `MCP_SCOPES` (OAuth scopes — under-scoping causes calls to fail with 403
`insufficient_scope` *after* discovery has already succeeded, which reads like a different bug),
and the OAuth consent screen's configured scopes in Google Cloud console. Tokens already issued
before a scope is added keep working with the old scope set — users must re-`/auth` to pick up a
newly required scope. `MCP_ENDPOINT_OVERRIDES` exists for servers whose registry-advertised URL is
simply wrong (currently `calendar`); check whether an override is still needed before trusting it
blindly, since Google may fix the registry entry without this repo noticing.

`Settings.mcp_timeout_seconds` (90s) and `mcp_cache_ttl_seconds` (1h) are tuned around observed
Workspace MCP latency (6–25s for a single `tools/list`) and the fact that ADK re-runs `list_tools`
on every LLM turn with no cross-request cache — don't lower either without measuring.

## User-connected ("custom") MCP servers (`agent/tools/custom_mcp.py`)

A user can paste an MCP server URL or a client JSON config block straight into the chat; its tools
become available on their next message, prefixed with the server's name. `/mcp` lists/removes them.
`CustomMcpToolset.get_tools()` resolves the *calling* user's servers per LLM turn (same pattern as
the Workspace `header_provider`), so the one shared agent instance serves each user's different tool
list. A pasted server is connected for real and asked for its tools before being saved, so a bad
URL/token fails once, visibly. Deliberate limits: remote servers only (no stdio/`command`, which
would mean executing something a chat message chose), https-only (localhost excepted), stored per
user and never shared. `Settings.custom_mcp_allowed_hosts` is empty (any https host) by default —
tightening it is a real trust decision since a pasted server's tools run in the same turn as the
user's Workspace tools and can see/steer off fetched data.

## Reply construction (`runner.py`, `chat/live_reply.py`, `chat/a2ui.py`, `chat/reply_attachment.py`)

A turn's raw text may carry one special payload appended after a marker: either an A2UI card
(buttons/images/layout on Cards v2) or a file the model wants sent back as an attachment — never
both by design. `runner.run_agent` strips the marker+JSON out of what's shown as the answer but
keeps it in the *returned* string for `chat/events.py` to parse and act on. Streaming
(`chat_streaming_enabled`) rewrites an in-place placeholder message as the model writes, throttled
by `chat_stream_interval_seconds` to stay inside Chat's per-minute write quota — not just for
smoothness.

## Voice (`agents/live_agent/`, `Settings.live_*`)

Speaking to the agent is a different wire protocol, not a setting: ADK's live mode holds one
bidirectional audio session open (`Runner.run_live`) and only Gemini's **Live** model family can
serve one — `gemini-3.8-flash` does not degrade there, it never connects. So `build_agent(live=True)`
swaps three things and nothing else: the model, its thinking budget, and the instruction. Same
tools, same everything else, on purpose — the confirm-before-writing rule and the treatment of MCP
output as data have to hold identically whether the user types or speaks.

- **The live model runs on a different backend from the rest of the app.**
  `gemini-3.1-flash-live-preview` (native audio in and out, no STT→LLM→TTS chain) is served only by
  the Gemini API (AI Studio); Vertex carries `gemini-live-2.5-flash-native-audio` under a different
  id. Since this app is on Vertex, `build_live_model` hands that one model its own
  `google.genai.Client` via ADK's `client_kwargs` (`vertexai=False` + `live_api_key`). Dropping the
  key is a valid second mode, but then `live_model` must be the Vertex id or the socket 404s.
- **The instruction is a prefix over the Chat one, not a copy** (`prompts.py::LIVE_PREFIX`). It has
  to override the Chat presentation layer specifically: `*bold*` is audible as "asterisk", and an
  A2UI/attachment marker line would be read out as JSON, since in live mode there is no `runner.py`
  between the model and the user to strip it back out.
- `live_thinking_level` is separate from `thinking_level` deliberately — thinking time that is
  invisible in Chat is dead air mid-sentence.
- The live model supports fewer capabilities than `model`: no `url_context`, no structured output,
  no caching. Web research still works because it is a sub-agent on `model`, called like any other
  function tool (`agent/tools/search.py`).
- Same anonymous limitation as `make dev`: `adk web` has no Chat user, so no Workspace tools.

## Configuration

Everything is env-driven (`GEMINI_ACT_` prefix, see `.env.example` and `config.py`); most values are
declared with the reasoning for their default inline as comments in `config.py` — read those before
changing one. A few with the widest blast radius:

- `thinking_level` — the single largest lever on reply latency: Gemini thinks on every LLM call, and
  a tool-using turn makes several of those.
- `chat_audience` / `public_base_url` — must exactly match the deployed Cloud Run URL (JWT audience
  and OAuth redirect base respectively); wrong values fail closed (401) or break `/oauth/callback`.
- `state_secret` — signs the OAuth `state`; a weak value lets someone bind their Google account to
  another Chat user's identity.
- `mcp_enabled` — each enabled Workspace server costs response time on every turn.

`deploy/deploy.sh` deploys twice on purpose: the service's own Cloud Run URL is both the
OAuth redirect base and the Chat JWT audience, so the first deploy exists only to learn the URL.
