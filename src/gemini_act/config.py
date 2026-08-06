"""Runtime configuration, read from the environment (or .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Remote Google Workspace MCP servers.
# https://developers.google.com/workspace/guides/configure-mcp-servers
MCP_SERVERS: dict[str, str] = {
    "gmail": "https://gmailmcp.googleapis.com/mcp/v1",
    "drive": "https://drivemcp.googleapis.com/mcp/v1",
    "docs": "https://docsmcp.googleapis.com/mcp/v1",
    "sheets": "https://sheetsmcp.googleapis.com/mcp/v1",
    "slides": "https://slidesmcp.googleapis.com/mcp/v1",
    "calendar": "https://calendarmcp.googleapis.com/mcp/v1",
    "chat": "https://chatmcp.googleapis.com/mcp/v1",
    "people": "https://people.googleapis.com/mcp/v1",
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
    "docs": (
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/documents",
    ),
    "sheets": (
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/spreadsheets",
    ),
    "slides": (
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/presentations",
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

# Always requested so we can identify the authorizing user.
BASE_OAUTH_SCOPES: tuple[str, ...] = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
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
    location: str = Field(default="us-central1", alias="GOOGLE_CLOUD_LOCATION")
    model: str = "gemini-3.6-flash"

    # Chat webhook
    chat_audience: str = ""
    verify_chat_requests: bool = True

    # OAuth
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    public_base_url: str = ""
    state_secret: str = "insecure-dev-secret"

    # Storage
    token_store: str = "firestore"
    firestore_collection: str = "gemini_act_tokens"
    session_db_url: str = ""

    # Capabilities
    mcp_enabled: tuple[str, ...] = ("gmail", "drive", "calendar", "chat", "docs")

    # Agent run budget, seconds. Chat's own sync window is ~30s, but we answer
    # asynchronously so the agent may take longer than that.
    agent_timeout_seconds: float = 180.0

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
