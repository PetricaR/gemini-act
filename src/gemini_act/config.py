"""Runtime configuration, read from the environment (or .env)."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Google Workspace MCP servers, resolved through Cloud Agent Registry rather than
# called directly at their public https://*mcp.googleapis.com/mcp/v1 URLs.
#
# The direct URLs belong to the Workspace MCP Developer Preview Program, which is
# allowlist-gated (https://developers.google.com/workspace/preview) — a project
# that is not enrolled gets a 403 on every call. Agent Registry
# (agentregistry.googleapis.com) exposes the same first-party servers under a
# different, broader entitlement and does not require that enrollment. See
# `agent/tools/workspace_mcp.py` for how these ids are resolved into toolsets.
#
# Values are the mcpServers/{id} segment under
# projects/{project}/locations/{location}/mcpServers/{id}. The Console's "Name"
# column (e.g. "gmailmcp.googleapis.com") is a display label, NOT the resource
# id — neither that string nor its short prefix ("gmailmcp") is a valid id (the
# API 400s on a "." in the segment, 404s on the bare prefix). The real id is an
# opaque, auto-generated string unique to this project's Agent Registry
# provisioning (agentregistry-00000000-0000-0000-XXXX-XXXXXXXXXXXX), found by
# listing and matching on displayName:
#
#   curl -H "Authorization: Bearer $(gcloud auth print-access-token)" \
#     "https://agentregistry.googleapis.com/v1/projects/${GOOGLE_CLOUD_PROJECT}/locations/global/mcpServers?pageSize=100"
#
# These values are therefore specific to the website-formare-ai project as
# provisioned on 2026-08-07 — re-run the listing above and update this table if
# ever pointed at a different GCP project. Only servers actually present in
# Agent Registry for this project are listed. Confirmed NOT registered here
# (checked twice, both times absent from the listing): Docs, Sheets, Slides,
# the universal "workspace" search server.
MCP_SERVERS: dict[str, str] = {
    "gmail": "agentregistry-00000000-0000-0000-694e-6cd3d0570769",
    "drive": "agentregistry-00000000-0000-0000-1ac8-248c78d4ed27",
    "calendar": "agentregistry-00000000-0000-0000-16d6-cee169897afc",
    "chat": "agentregistry-00000000-0000-0000-263a-52b590fe274c",
    "people": "agentregistry-00000000-0000-0000-30c9-08a2641d3196",
    "bigquery": "agentregistry-00000000-0000-0000-1169-26595affcf5c",
    "maps": "agentregistry-00000000-0000-0000-087b-e3d7f8e1001a",
    "storage": "agentregistry-00000000-0000-0000-2d58-34bf4b09480a",
}

# Endpoint URLs to use instead of the one Agent Registry advertises, per server.
#
# Normally the registry entry's `interfaces[].url` is authoritative and this map
# is empty. Calendar is currently an exception: its entry advertises
# https://calendarmcp.googleapis.com/mcp, which answers 404 to every request,
# while the server actually lives at /mcp/v1 like the other Workspace servers.
# The effect is not a degraded Calendar — it is no Calendar at all, on every
# turn, since the toolset fails at `initialize` and never lists a single tool.
#
# Verified 2026-08-08 by POSTing `initialize` to both paths for all eight
# registered servers: only Calendar's registry URL is wrong. The rest split
# between /mcp/v1 (gmail, drive, chat, people), /mcp (bigquery, maps) and
# /storage/mcp (storage), each matching what its entry advertises — so this is a
# per-server registry data bug, not a version convention we can infer.
#
# Re-probe before assuming this is still needed: the fix belongs on Google's
# side, and once the entry is corrected this override silently keeps working
# (same URL) but should be dropped.
MCP_ENDPOINT_OVERRIDES: dict[str, str] = {
    "calendar": "https://calendarmcp.googleapis.com/mcp/v1",
}

# OAuth scopes requested from the end user, per MCP server. Taken from the
# Workspace MCP configuration guide; keep these in sync with the scopes added to
# the OAuth consent screen or authorization will fail at runtime.
MCP_SCOPES: dict[str, tuple[str, ...]] = {
    "gmail": (
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
    ),
    "drive": (
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.file",
    ),
    "calendar": (
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
        # Needed by suggest_time (freebusy.query); calendar.events does NOT
        # cover it, nor does calendarlist.readonly cover list_calendars — the
        # three below are disjoint, none is redundant.
        "https://www.googleapis.com/auth/calendar.events.freebusy",
        # Read *and write* on events, replacing calendar.events.readonly (of
        # which it is a superset). This server exposes create_event,
        # update_event, delete_event and respond_to_event, so read-only left the
        # model offering four actions it could only ever fail at, with the same
        # insufficient_scope 403 that hid the Maps bug.
        #
        # Deliberately not the broader .../auth/calendar: that additionally
        # grants creating and deleting whole calendars, which no tool here does.
        # Confirmed from both directions — the Calendar v3 discovery doc lists
        # calendar.events as accepted for events.insert/update/patch/delete, and
        # the MCP server's own 403 on create_event names it in WWW-Authenticate.
        "https://www.googleapis.com/auth/calendar.events",
    ),
    "chat": (
        "https://www.googleapis.com/auth/chat.spaces.readonly",
        "https://www.googleapis.com/auth/chat.memberships.readonly",
        "https://www.googleapis.com/auth/chat.messages.readonly",
        "https://www.googleapis.com/auth/chat.messages.create",
    ),
    "people": (
        "https://www.googleapis.com/auth/directory.readonly",
        "https://www.googleapis.com/auth/contacts.readonly",
    ),
    # Verified against the BigQuery API discovery doc: jobs.query (which backs
    # this server's execute_sql/execute_sql_readonly tools) only accepts
    # bigquery / cloud-platform / cloud-platform.read-only — bigquery.readonly
    # is not in that list, so it would not actually let the model run queries.
    "bigquery": ("https://www.googleapis.com/auth/bigquery",),
    # Maps' tools act on Maps Platform/place data rather than the end user's
    # personal Google data, but the server still gates them behind its own
    # scope: cloud-platform alone gets `initialize` and `tools/list` through
    # (which is why discovery succeeds and only the actual tool call fails),
    # then `tools/call` returns 403 with
    #   WWW-Authenticate: Bearer error="insufficient_scope",
    #     scope="https://www.googleapis.com/auth/maps-platform.mapstools"
    # Taken from that header, i.e. named by the server itself, not guessed.
    "maps": ("https://www.googleapis.com/auth/maps-platform.mapstools",),
    # Verified against the Cloud Storage API discovery doc. read_only would be
    # insufficient: this server's tools include create_bucket, write_text and
    # delete_object, which need read_write.
    "storage": ("https://www.googleapis.com/auth/devstorage.read_write",),
}

# Always requested.
#
# cloud-platform is required, not optional: calling a Workspace MCP server needs
# the IAM permission `mcp.tools.call` (roles/mcp.toolUser) on the Cloud project,
# and IAM is only evaluated when the token carries this scope. Without it every
# tool call fails with "The caller does not have permission", which reads like a
# Workspace consent problem and is not one. Google's own Workspace MCP codelab
# requests it first for the same reason.
#
# It is a broad scope — it grants the agent the user's Google Cloud access — so
# the grant is worth being deliberate about. It is the documented requirement.
BASE_OAUTH_SCOPES: tuple[str, ...] = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cloud-platform",
    # Full read/write/delete over the user's own Chat messages, as the user —
    # distinct from CHAT_BOT_SCOPE below, which only ever acts as the app.
    # Requested unconditionally (not gated on `chat` being in mcp_enabled)
    # because /clean uses it directly, independent of the Chat MCP toolset.
    # The app's own messages are deleted with its own identity and never need
    # this; this is only for deleting the *user's* own messages on request.
    "https://www.googleapis.com/auth/chat.messages",
)

# Scope the app itself uses to post messages as the Chat app (service account).
CHAT_BOT_SCOPE = "https://www.googleapis.com/auth/chat.bot"

# Accepted values for `Settings.thinking_level`, mirroring
# google.genai.types.ThinkingLevel minus its UNSPECIFIED placeholder. Kept as
# plain strings so this module stays free of a genai import; the conversion to
# the enum happens in `agent/factory.py`.
THINKING_LEVELS: frozenset[str] = frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GEMINI_ACT_",
        env_file=".env",
        extra="ignore",
    )

    # Vertex AI. These two are read by ADK under their unprefixed names, so they
    # are declared with explicit aliases rather than the GEMINI_ACT_ prefix.
    project: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")
    # Gemini 3.x is served from the `global` Vertex endpoint, not a regional one —
    # gemini-3.6-flash 404s in europe-west1 and resolves at global. This is
    # independent of the Cloud Run region and of where Firestore lives.
    location: str = Field(default="global", alias="GOOGLE_CLOUD_LOCATION")
    model: str = "gemini-3.6-flash"
    # How hard the model thinks before it answers. This is the single largest
    # lever on how long a user waits: Gemini 3.x thinks on *every* LLM call, and
    # one turn that uses tools is several of those, so the cost is paid three to
    # five times per reply — not once.
    #
    # LOW still plans multi-step tool use correctly while cutting most of that
    # latency. MINIMAL is faster again but starts fumbling anything needing more
    # than one tool call. Raise to MEDIUM/HIGH if answers turn shallow; an empty
    # value leaves the model's own default in place (which is what this service
    # ran with before, and why replies took as long as they did).
    thinking_level: str = "LOW"

    # Chat webhook
    chat_audience: str = ""
    verify_chat_requests: bool = True
    # Numeric GCP project number. Used to pin the Workspace add-on token issuer
    # (service-<number>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com). Leave empty
    # only for classic Chat apps, which are issued by chat@system instead.
    project_number: str = ""
    # Where the asynchronous answer lands. False (the default) posts it as a new
    # top-level message, so the conversation reads as one flat running stream in
    # the main window — the WhatsApp-style layout people expect from a chat bot.
    # True attaches it to a thread instead, which Chat renders as a collapsed
    # "N replies" bubble the user has to expand; only useful in a named space
    # where several topics run in parallel. See `chat/events.py::_post_reply`.
    chat_reply_in_thread: bool = False
    # Stream the answer instead of delivering it in one piece. Chat has no
    # typing indicator an app can raise, so this is built from a placeholder
    # posted the moment the question arrives, rewritten in place as the model
    # writes — see `chat/live_reply.py`. Turning it off restores the single
    # message at the end, and the silence that comes with it.
    chat_streaming_enabled: bool = True
    # Minimum seconds between rewrites of the in-flight message. Every rewrite
    # is a Chat API write against the space's per-minute quota, so this is a
    # rate limit first and a smoothness knob second. 1.5s caps a streaming reply
    # at ~40 writes/minute, which leaves the space room for the humans in it; at
    # 1.0s a single long answer would sit on the quota on its own.
    chat_stream_interval_seconds: float = 1.5

    # OAuth
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    public_base_url: str = ""
    state_secret: str = "insecure-dev-secret"

    # Storage
    token_store: str = "firestore"
    firestore_collection: str = "gemini_act_tokens"
    firestore_mcp_collection: str = "gemini_act_mcp_servers"
    session_db_url: str = ""

    # User-connected MCP servers: paste a server URL (or a client's JSON config
    # block) into the chat and its tools join that user's next turn. Per user —
    # one person's servers are never visible to another.
    custom_mcp_enabled: bool = True
    custom_mcp_max_per_user: int = 10
    # Hosts a pasted server may live on, as bare hostnames ("mcp.example.com");
    # a leading dot is not needed, subdomains of a listed host are accepted.
    # Empty (the default) accepts any https host, which is a real trust
    # decision: the tools of whatever server a user pastes run inside the same
    # agent turn as their Workspace tools, so a hostile server can both read
    # what the agent has fetched and return text that tries to steer it. Set
    # this to lock the feature down to servers you vet.
    custom_mcp_allowed_hosts: Annotated[tuple[str, ...], NoDecode] = ()

    # Capabilities. NoDecode is required: without it pydantic-settings tries to
    # JSON-decode this env var before the validator below runs, so the plain CSV
    # form ("gmail,drive") raises at startup.
    mcp_enabled: Annotated[tuple[str, ...], NoDecode] = (
        "gmail",
        "drive",
        "calendar",
        "chat",
        "people",
        "bigquery",
        "maps",
        "storage",
    )

    # Agent run budget, seconds. Chat's own sync window is ~30s, but we answer
    # asynchronously so the agent may take longer than that.
    agent_timeout_seconds: float = 180.0

    # Per-call budget for the Workspace MCP servers. ADK's default is 5s, which
    # these servers routinely exceed — observed 6-25s for a single tools/list,
    # so every toolset timed out and the agent silently lost its Workspace
    # tools. Do not lower this without measuring.
    mcp_timeout_seconds: float = 90.0

    # How long a server's tool list is reused. ADK re-runs list_tools on every
    # LLM turn and has no cross-request cache (google/adk-python#3659), which at
    # these servers' latency dominates the agent's budget. Tool definitions are
    # effectively static, so an hour is safe.
    mcp_cache_ttl_seconds: float = 3600.0

    @field_validator("mcp_enabled", "custom_mcp_allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("thinking_level", mode="before")
    @classmethod
    def _normalise_thinking_level(cls, value: object) -> object:
        """Accept `low`/`Low`/`LOW`, and fail at startup on a typo.

        An unrecognised level would otherwise raise deep inside the first agent
        turn, surfacing to the user as a generic "unexpected error".
        """
        if not isinstance(value, str):
            return value
        level = value.strip().upper()
        if level and level not in THINKING_LEVELS:
            raise ValueError(
                f"Unknown thinking level: {value}. Known: {', '.join(sorted(THINKING_LEVELS))} "
                "(or empty to use the model default)"
            )
        return level

    @field_validator("mcp_enabled", mode="after")
    @classmethod
    def _known_servers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - MCP_SERVERS.keys())
        if unknown:
            raise ValueError(
                f"Unknown MCP server(s): {', '.join(unknown)}. "
                f"Known: {', '.join(sorted(MCP_SERVERS))}"
            )
        return value

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/oauth/callback"

    @property
    def oauth_scopes(self) -> list[str]:
        """Every scope we ask the user to grant, deduplicated and ordered."""
        scopes = list(BASE_OAUTH_SCOPES)
        for server in self.mcp_enabled:
            for scope in MCP_SCOPES.get(server, ()):
                if scope not in scopes:
                    scopes.append(scope)
        return scopes


@lru_cache
def get_settings() -> Settings:
    return Settings()
