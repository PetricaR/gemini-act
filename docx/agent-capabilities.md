# Gemini Act — Current Capabilities

Snapshot as of 2026-08-08, for the `website-formare-ai` deployment. Reflects what is actually wired
in and enabled by default (`Settings.mcp_enabled`), not what is theoretically possible — see
[workspace-mcp-agent-registry.md](workspace-mcp-agent-registry.md) for how the Workspace tools are
resolved and their known gaps.

## What it is

An ADK agent that lives in Google Chat and takes real actions in Google Workspace on a user's
behalf — not a Q&A bot. It acts using the calling user's own OAuth-granted permissions (three-legged
OAuth), so it can only do what that person could already do themselves.

## How to talk to it

- **DM (1:1)** — one continuous conversation in the main window, like any messaging app; the
  agent remembers context across messages.
- **Named Space / group chat** — memory is per thread, so separate topics stay separate.
- First message from a new user gets an auth prompt (`/auth`) before any Workspace tool can run.

### Slash commands

| Command | What it does |
| --- | --- |
| `/help` | Shows the welcome card and this command list |
| `/auth` | Connect or reconnect your Google account (re-run after scopes change) |
| `/reset` | Forget this conversation's memory — the agent starts fresh, messages stay visible |
| `/clean` | Delete every message in the conversation (yours and the bot's) and reset memory |
| `/whoami` | Show which Google account the agent is currently acting as |
| `/mcp` | List your own MCP servers; `/mcp add <url or config>`, `/mcp remove <name>` |

## Bring your own tools

Paste a remote MCP server's URL — or the JSON config block a vendor hands you — into the chat and
the agent connects it and keeps it. Its tools show up on your next message, named after the server
(`acme_search`), and they are yours alone: servers are stored per Chat user, so connecting one
changes nothing for anyone else and needs no redeploy.

The server is contacted and asked for its tool list before it is saved, so a wrong URL or a stale
token fails immediately with the reason rather than degrading later turns. Remote https servers
only — a stdio config (`"command": "npx"`) is refused, since running it would mean executing a
command chosen by a chat message inside the agent's container.

Results from these servers are third-party data, and the agent is instructed to treat them as data
rather than instructions. A deployment that wants a hard boundary sets
`GEMINI_ACT_CUSTOM_MCP_ALLOWED_HOSTS` to the hosts it trusts.

## Business tools (always available, no auth needed)

Worked examples in [`agent/tools/business.py`](../src/gemini_act/agent/tools/business.py) — stand-ins
for real internal integrations:

- **`current_time(timezone)`** — current date/time in any IANA timezone.
- **`lookup_reference_data(entity, identifier)`** — looks up a record in an internal reference
  system (currently a two-row stub: one `store`, one `product`).
- **`summarize_numbers(values, label)`** — count/total/mean/min/max over a list of numbers.

## Web search (always available, no auth needed)

Google Search grounding — the model's own built-in web search, for questions that fall
outside Workspace and the business tools (current events, public facts, anything not in the
user's own data). Wired in [`agent/tools/search.py`](../src/gemini_act/agent/tools/search.py)
as `GoogleSearchTool(bypass_multi_tools_limit=True)`, ADK's documented way to combine it with
other tools: Gemini's built-in `google_search` cannot share a request with custom
function-declaration tools, so ADK runs it inside its own single-tool sub-agent and exposes
that sub-agent to the root agent as an ordinary callable tool (`google_search_agent`). Needs
no per-user OAuth — it is a model-native capability, not a Workspace call — but each search
adds an LLM round trip and is billed separately on Vertex AI, so it is a toggle
(`Settings.web_search_enabled`, default on) rather than an always-on business tool.

## Chat tools (act as the app itself, not the user)

[`agent/tools/chat_tools.py`](../src/gemini_act/agent/tools/chat_tools.py) — for when the app should
be the visible actor (announcements), as opposed to the Workspace `chat` MCP tools below, which act
as the user:

- **`post_message_to_space(space, text)`** — post into a space the app is a member of.
- **`list_space_members(space)`** — list a space's members.
- **`list_app_spaces()`** — list spaces the app belongs to.

## Workspace tools (act as the user, via Cloud Agent Registry)

Three-legged OAuth — every call carries the calling user's own access token and permissions.
Enabled by default: `gmail`, `drive`, `calendar`, `chat`, `people`, `bigquery`, `maps`, `storage`.
Not available for this project: Docs, Sheets, Slides (see Known limitations).

### Gmail (27 tools)

Read: `list_threads`, `search_threads`, `get_thread`, `list_labels`, `list_filters`,
`get_message_attachment`, `download_attachment`, `read_attachment`.
Write: `create_draft`, `update_draft`, `send_message`, `reply`, `forward`, `label_thread`,
`unlabel_thread`, `batch_label_threads`, `batch_unlabel_threads`, `label_message`,
`unlabel_message`, `batch_label_messages`, `batch_unlabel_messages`, `list_drafts`, `create_label`,
`update_label`, `delete_label`, `create_filter`, `delete_filter`.

### Drive (11 tools)

`search_files`, `list_recent_files`, `get_file_metadata`, `get_file_permissions`,
`read_file_content`, `download_file_content`, `create_file`, `copy_file`, `update_file`,
`share_file`, `trash_file`.

### Calendar (8 tools) — currently broken, see Known limitations

`list_calendars`, `list_events`, `get_event`, `suggest_time`, `create_event`, `update_event`,
`delete_event`, `respond_to_event`.

### Chat, as the user (4 tools)

Distinct from the app-identity Chat tools above — these read/send *as the calling user*:
`list_messages`, `search_messages`, `search_conversations`, `send_message`.

### People (3 tools)

`get_user_profile`, `search_contacts`, `search_directory_people` (org directory).

### BigQuery (6 tools)

`list_dataset_ids`, `get_dataset_info`, `list_table_ids`, `get_table_info`,
`execute_sql_readonly` (preferred), `execute_sql`.

### Maps (5 tools)

`search_places`, `lookup_weather`, `compute_routes`, `resolve_names`, `resolve_maps_urls`. Not
gated on the user's personal data — no extra OAuth scope beyond the base grant.

### Cloud Storage (9 tools)

Read: `list_buckets`, `list_objects`, `get_object_metadata`, `read_text`, `read_object`.
Write: `create_bucket`, `write_text`, `delete_object`.

## Known limitations

- **Calendar is currently broken.** The registered endpoint
  (`https://calendarmcp.googleapis.com/mcp`) 404s on every call; the agent silently drops the
  calendar toolset and continues without it rather than failing the whole turn. Root cause not yet
  diagnosed — the other seven servers all resolve and work.
- **Docs, Sheets, Slides are not available.** Confirmed absent from this project's Agent Registry
  listing (checked more than once) — not a configuration mistake, they are simply not registered
  here. No known workaround yet.
- **`/clean` needs one extra OAuth grant.** Deleting a user's own Chat messages requires the
  `chat.messages` scope; anyone who authorized before this was added needs to run `/auth` again, or
  `/clean` will only remove the bot's own messages and ask them to reconnect.
- **First reply after a cold start is slow** (~10s+): building the agent resolves all eight
  Workspace toolsets through Agent Registry and does a live `tools/list` per server. Cached for an
  hour after that (`mcp_cache_ttl_seconds`).

## Where this is defined

- `src/gemini_act/config.py` — `MCP_SERVERS` (which servers, their Agent Registry ids),
  `MCP_SCOPES` (OAuth scopes per server), `Settings.mcp_enabled` (which are actually turned on).
- `src/gemini_act/agent/factory.py` — assembles all tool groups (business, chat, web search,
  Workspace MCP, custom MCP) onto one `Agent`.
- `src/gemini_act/agent/prompts.py` — the system instruction governing *how* it uses these tools
  (ask before destructive actions, never invent causes for tool failures, etc.).
