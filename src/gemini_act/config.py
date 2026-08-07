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
# projects/{project}/locations/{location}/mcpServers/{id}. Only servers actually
# present in Agent Registry for this project are listed; Docs/Sheets/Slides/the
# universal "workspace" search server are not registered here and are omitted.
MCP_SERVERS: dict[str, str] = {
    "gmail": "gmailmcp",
    "drive": "drivemcp",
    "calendar": "calendarmcp",
    "chat": "chatmcp",
    "people": "people",
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
        "https://www.googleapis.com/auth/calendar.events.freebusy",
        "https://www.googleapis.com/auth/calendar.events.readonly",
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
)

# Scope the app itself uses to post messages as the Chat app (service account).
CHAT_BOT_SCOPE = "https://www.googleapis.com/auth/chat.bot"


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

    # Chat webhook
    chat_audience: str = ""
    verify_chat_requests: bool = True
    # Numeric GCP project number. Used to pin the Workspace add-on token issuer
    # (service-<number>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com). Leave empty
    # only for classic Chat apps, which are issued by chat@system instead.
    project_number: str = ""

    # OAuth
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    public_base_url: str = ""
    state_secret: str = "insecure-dev-secret"

    # Storage
    token_store: str = "firestore"
    firestore_collection: str = "gemini_act_tokens"
    session_db_url: str = ""

    # Capabilities. NoDecode is required: without it pydantic-settings tries to
    # JSON-decode this env var before the validator below runs, so the plain CSV
    # form ("gmail,drive") raises at startup.
    mcp_enabled: Annotated[tuple[str, ...], NoDecode] = (
        "gmail",
        "drive",
        "calendar",
        "chat",
        "people",
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

    @field_validator("mcp_enabled", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

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
