"""Persistence for the MCP servers a user has connected themselves.

Kept per Chat user id, in the same spirit as `oauth/store.py`: the servers one
person adds are theirs, not the deployment's, and nobody else's turns see them.
A server's config can carry a bearer token, so this is credential storage —
treated with the same care as the OAuth collection and never logged.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from gemini_act.config import Settings, get_settings
from gemini_act.mcp.spec import McpServerSpec, McpSpecError

logger = logging.getLogger(__name__)


class McpServerStore(Protocol):
    """Persistence for a user's connected servers, keyed by Chat user id."""

    async def get(self, user_id: str) -> list[McpServerSpec]: ...

    async def put(self, user_id: str, servers: list[McpServerSpec]) -> None: ...


@dataclass
class InMemoryMcpServerStore:
    """Non-persistent store for local development and tests."""

    _servers: dict[str, list[McpServerSpec]] = field(default_factory=dict)

    async def get(self, user_id: str) -> list[McpServerSpec]:
        return list(self._servers.get(user_id, []))

    async def put(self, user_id: str, servers: list[McpServerSpec]) -> None:
        self._servers[user_id] = list(servers)


class FirestoreMcpServerStore:
    """Firestore-backed store. The client is sync, so calls are off-thread."""

    def __init__(self, collection: str, project: str = "") -> None:
        from google.cloud import firestore

        self._client = firestore.Client(project=project or None)
        self._collection = collection

    def _doc(self, user_id: str):
        # Chat user ids look like "users/1234"; '/' is not allowed in a doc id.
        return self._client.collection(self._collection).document(user_id.replace("/", "_"))

    async def get(self, user_id: str) -> list[McpServerSpec]:
        snapshot = await asyncio.to_thread(self._doc(user_id).get)
        if not snapshot.exists:
            return []
        raw = (snapshot.to_dict() or {}).get("servers") or []
        servers: list[McpServerSpec] = []
        for entry in raw:
            try:
                servers.append(McpServerSpec.from_dict(entry))
            except (KeyError, TypeError, ValueError):
                # A record written by an older shape should cost one server, not
                # every server this user has.
                logger.warning("Skipping unreadable MCP server record for %s", user_id)
        return servers

    async def put(self, user_id: str, servers: list[McpServerSpec]) -> None:
        payload = {"servers": [spec.to_dict() for spec in servers]}
        await asyncio.to_thread(self._doc(user_id).set, payload)


def build_mcp_server_store(settings: Settings) -> McpServerStore:
    if settings.token_store == "memory":
        return InMemoryMcpServerStore()
    return FirestoreMcpServerStore(settings.firestore_mcp_collection, settings.project)


class McpRegistry:
    """A user's connected servers, with the rules about changing that list."""

    def __init__(self, store: McpServerStore, settings: Settings) -> None:
        self._store = store
        self._settings = settings
        # One lock per user: two messages arriving together must not each
        # read-modify-write the list and lose one of the two edits.
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def store(self) -> McpServerStore:
        return self._store

    def _lock_for(self, user_id: str) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    async def list(self, user_id: str) -> list[McpServerSpec]:
        if not user_id:
            return []
        return await self._store.get(user_id)

    async def add(self, user_id: str, spec: McpServerSpec) -> bool:
        """Save a server. Returns True when it replaced one of the same name.

        Raises:
            McpSpecError: when the user is already at the per-user limit.
        """
        async with self._lock_for(user_id):
            servers = await self._store.get(user_id)
            kept = [existing for existing in servers if existing.name != spec.name]
            replaced = len(kept) != len(servers)
            limit = self._settings.custom_mcp_max_per_user
            if not replaced and len(kept) >= limit:
                raise McpSpecError(
                    f"You already have {len(kept)} servers connected, which is the limit "
                    f"({limit}). Remove one with /mcp remove <name> first."
                )
            await self._store.put(user_id, [*kept, spec])
            return replaced

    async def remove(self, user_id: str, name: str) -> bool:
        """Drop a server by name. Returns False when there was no such server."""
        async with self._lock_for(user_id):
            servers = await self._store.get(user_id)
            kept = [spec for spec in servers if spec.name != name]
            if len(kept) == len(servers):
                return False
            await self._store.put(user_id, kept)
            return True

    async def clear(self, user_id: str) -> int:
        async with self._lock_for(user_id):
            servers = await self._store.get(user_id)
            if servers:
                await self._store.put(user_id, [])
            return len(servers)


@lru_cache
def get_mcp_registry() -> McpRegistry:
    settings = get_settings()
    return McpRegistry(build_mcp_server_store(settings), settings)
