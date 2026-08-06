"""Storage and refresh of per-user Google OAuth credentials.

The Chat event tells us *who* is talking to the app, but carries no token for
them. The Workspace MCP servers are three-legged OAuth, so we run our own
consent flow and keep the resulting refresh token here, keyed by Chat user id.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Protocol

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials

from gemini_act.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Refresh a little early so a token cannot expire mid tool-call.
_EXPIRY_SKEW = timedelta(minutes=5)


@dataclass
class StoredToken:
    """A user's credentials as persisted."""

    refresh_token: str
    scopes: list[str]
    email: str = ""
    access_token: str = ""
    expiry: datetime | None = None

    def is_fresh(self) -> bool:
        if not self.access_token or self.expiry is None:
            return False
        return datetime.now(UTC) < self.expiry - _EXPIRY_SKEW

    def has_scopes(self, required: tuple[str, ...]) -> bool:
        return set(required).issubset(self.scopes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "refresh_token": self.refresh_token,
            "scopes": self.scopes,
            "email": self.email,
            "access_token": self.access_token,
            "expiry": self.expiry.isoformat() if self.expiry else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredToken:
        expiry = data.get("expiry")
        if isinstance(expiry, str):
            expiry = datetime.fromisoformat(expiry)
        elif isinstance(expiry, datetime):
            pass
        else:
            expiry = None
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return cls(
            refresh_token=data["refresh_token"],
            scopes=list(data.get("scopes", [])),
            email=data.get("email", ""),
            access_token=data.get("access_token", ""),
            expiry=expiry,
        )


class TokenStore(Protocol):
    """Persistence for user credentials, keyed by Chat user id."""

    async def get(self, user_id: str) -> StoredToken | None: ...

    async def put(self, user_id: str, token: StoredToken) -> None: ...

    async def delete(self, user_id: str) -> None: ...


@dataclass
class InMemoryTokenStore:
    """Non-persistent store for local development and tests."""

    _tokens: dict[str, StoredToken] = field(default_factory=dict)

    async def get(self, user_id: str) -> StoredToken | None:
        return self._tokens.get(user_id)

    async def put(self, user_id: str, token: StoredToken) -> None:
        self._tokens[user_id] = token

    async def delete(self, user_id: str) -> None:
        self._tokens.pop(user_id, None)


class FirestoreTokenStore:
    """Firestore-backed store. The client is sync, so calls are off-thread."""

    def __init__(self, collection: str, project: str = "") -> None:
        from google.cloud import firestore

        self._client = firestore.Client(project=project or None)
        self._collection = collection

    def _doc(self, user_id: str):
        # Chat user ids look like "users/1234"; '/' is not allowed in a doc id.
        return self._client.collection(self._collection).document(user_id.replace("/", "_"))

    async def get(self, user_id: str) -> StoredToken | None:
        snapshot = await asyncio.to_thread(self._doc(user_id).get)
        if not snapshot.exists:
            return None
        return StoredToken.from_dict(snapshot.to_dict() or {})

    async def put(self, user_id: str, token: StoredToken) -> None:
        await asyncio.to_thread(self._doc(user_id).set, token.to_dict())

    async def delete(self, user_id: str) -> None:
        await asyncio.to_thread(self._doc(user_id).delete)


def build_token_store(settings: Settings) -> TokenStore:
    if settings.token_store == "memory":
        return InMemoryTokenStore()
    return FirestoreTokenStore(settings.firestore_collection, settings.project)


class TokenService:
    """Hands out live access tokens, refreshing against Google as needed."""

    def __init__(self, store: TokenStore, settings: Settings) -> None:
        self._store = store
        self._settings = settings
        # One lock per user so concurrent tool calls refresh only once.
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def store(self) -> TokenStore:
        return self._store

    def _lock_for(self, user_id: str) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    async def get_token(self, user_id: str) -> StoredToken | None:
        """The user's stored credentials, or None if they have not authorized."""
        return await self._store.get(user_id)

    async def get_access_token(self, user_id: str) -> str | None:
        """A currently-valid access token, or None if the user has not authorized."""
        stored = await self._store.get(user_id)
        if stored is None:
            return None
        if stored.is_fresh():
            return stored.access_token

        async with self._lock_for(user_id):
            # Another waiter may have refreshed while we queued.
            stored = await self._store.get(user_id)
            if stored is None:
                return None
            if stored.is_fresh():
                return stored.access_token
            try:
                refreshed = await asyncio.to_thread(self._refresh, stored)
            except Exception:
                logger.exception("Token refresh failed for %s", user_id)
                return None
            await self._store.put(user_id, refreshed)
            return refreshed.access_token

    def _refresh(self, stored: StoredToken) -> StoredToken:
        credentials = Credentials(
            token=None,
            refresh_token=stored.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._settings.oauth_client_id,
            client_secret=self._settings.oauth_client_secret,
            scopes=stored.scopes,
        )
        credentials.refresh(GoogleAuthRequest())
        expiry = credentials.expiry
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return StoredToken(
            # Google only returns a refresh token on first consent; keep ours.
            refresh_token=credentials.refresh_token or stored.refresh_token,
            scopes=stored.scopes,
            email=stored.email,
            access_token=credentials.token or "",
            expiry=expiry,
        )


@lru_cache
def get_token_service() -> TokenService:
    settings = get_settings()
    return TokenService(build_token_store(settings), settings)
