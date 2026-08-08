"""Reading an MCP server out of whatever the user pasted into the chat.

People do not paste a tidy record. They paste a bare URL, or the JSON block
from a vendor's "add to your client" instructions, or that block wrapped in a
markdown fence, or a Claude Desktop config with three servers in it. All of
those describe the same thing, so all of them are accepted here and normalised
into `McpServerSpec`.

Everything that could go wrong is raised as `McpSpecError` carrying a message
written for the person in the chat, not for a log: the caller posts `str(exc)`
straight back to them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

# What the config key for the transport can say, mapped onto the two remote
# transports MCP actually has. Clients disagree on the spelling ("type" vs
# "transport", "http" vs "streamable-http"), so accept the spread.
_TRANSPORTS = {
    "http": "http",
    "https": "http",
    "streamable-http": "http",
    "streamable_http": "http",
    "streamablehttp": "http",
    "streamable": "http",
    "sse": "sse",
}

# The key holding a {name: config} map, across the popular clients: Claude
# Desktop and Cursor use "mcpServers", VS Code uses "servers".
_SERVER_MAP_KEYS = ("mcpServers", "servers", "mcp_servers")

# Where a config might put the URL.
_URL_KEYS = ("url", "serverUrl", "endpoint", "uri")

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Host labels that say nothing about *which* server this is, so they make poor
# tool-name prefixes.
_GENERIC_LABELS = frozenset({"mcp", "api", "www", "server", "app"})

_OPENING_FENCE = re.compile(r"\A\s*```[a-zA-Z0-9_+-]*[ \t]*\r?\n?")
_CLOSING_FENCE = re.compile(r"\r?\n?\s*```\s*\Z")
_NON_SLUG = re.compile(r"[^a-z0-9]+")

# Chat likes to decorate a pasted link, and people add trailing punctuation.
_URL_TRIM = "<>`'\",;.()[]"

_MAX_NAME_LENGTH = 24


class McpSpecError(ValueError):
    """A pasted MCP server could not be understood, or is not allowed here.

    The message is user-facing: it gets posted back into the chat verbatim.
    """


@dataclass(frozen=True)
class McpServerSpec:
    """One remote MCP server a user has asked the agent to use.

    `name` doubles as the tool-name prefix the model sees, so it is always a
    slug: lowercase, `[a-z0-9_]`, starting with a letter.
    """

    name: str
    url: str
    transport: str = "http"
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Identity of the *connection*, for caching a live toolset per config.

        Headers are part of it: two users may paste the same URL with different
        credentials, and those must not share an upstream session. Hashed
        because the headers usually hold a token and this ends up in log lines
        and dict keys.
        """
        material = json.dumps(
            [self.name, self.url, self.transport, sorted(self.headers.items())],
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode()).hexdigest()[:16]

    @property
    def host(self) -> str:
        return (urlparse(self.url).hostname or "").lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "transport": self.transport,
            "headers": dict(self.headers),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> McpServerSpec:
        headers = data.get("headers") or {}
        return cls(
            name=data["name"],
            url=data["url"],
            transport=data.get("transport") or "http",
            headers={str(k): str(v) for k, v in dict(headers).items()},
        )


def strip_code_fences(text: str) -> str:
    """Drop a surrounding ``` fence, which a pasted config usually arrives in."""
    body = text.strip()
    if body.startswith("```"):
        body = _OPENING_FENCE.sub("", body)
        body = _CLOSING_FENCE.sub("", body)
    return body.strip()


def looks_like_mcp_config(text: str) -> bool:
    """Whether a message is a user handing us an MCP server, not a question.

    Deliberately narrow: a message is only claimed when it is *nothing but* a
    server. A lone link needs an MCP-shaped host or path, so "summarise
    https://example.com/post" and a pasted article URL still reach the model.
    A stdio config counts as a match even though it cannot be connected —
    better to explain why than to hand `npx -y some-server` to the model.
    """
    body = strip_code_fences(text)
    if not body:
        return False

    if body.startswith("{"):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return False
        if not isinstance(data, dict):
            return False
        if any(key in data for key in _SERVER_MAP_KEYS):
            return True
        return "command" in data or any(key in data for key in _URL_KEYS)

    tokens = body.split()
    if len(tokens) != 1:
        return False
    parsed = urlparse(tokens[0].strip(_URL_TRIM))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    path = parsed.path.rstrip("/").lower()
    return (
        host.startswith("mcp.")
        or host.startswith("mcp-")
        or path.endswith("/mcp")
        or path.endswith("/sse")
        or path.endswith("/mcp/v1")
        or "/mcp/" in f"{path}/"
    )


def parse_mcp_config(text: str, *, allowed_hosts: tuple[str, ...] = ()) -> list[McpServerSpec]:
    """Every server described by `text`, validated.

    Raises:
        McpSpecError: with a message meant to be shown to the user.
    """
    body = strip_code_fences(text)
    if not body:
        raise McpSpecError("You didn't give me a server. Paste its URL, or its JSON config.")

    if body.startswith("{"):
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise McpSpecError(
                f"That looks like an MCP config but it isn't valid JSON: {exc.msg} "
                f"(line {exc.lineno}, column {exc.colno})."
            ) from exc
        specs = _specs_from_json(data, allowed_hosts)
    else:
        specs = [_spec_from_url(body, allowed_hosts)]

    if not specs:
        raise McpSpecError("That config doesn't describe any server I can connect to.")
    return _deduplicate_names(specs)


def _spec_from_url(body: str, allowed_hosts: tuple[str, ...]) -> McpServerSpec:
    tokens = body.split()
    if len(tokens) > 1:
        raise McpSpecError(
            "I expected either a single MCP server URL or a JSON config, and got "
            f"{len(tokens)} words. If the URL is right, paste it on its own."
        )
    url = _validate_url(tokens[0].strip(_URL_TRIM), allowed_hosts)
    return McpServerSpec(name=_name_from_url(url), url=url, transport=_transport_from_url(url))


def _specs_from_json(data: Any, allowed_hosts: tuple[str, ...]) -> list[McpServerSpec]:
    if not isinstance(data, dict):
        raise McpSpecError("An MCP config has to be a JSON object.")

    for key in _SERVER_MAP_KEYS:
        servers = data.get(key)
        if isinstance(servers, dict):
            return [
                _spec_from_config(name, config, allowed_hosts) for name, config in servers.items()
            ]
        if servers is not None:
            raise McpSpecError(f'"{key}" should be an object of name → server config.')

    if any(field_name in data for field_name in (*_URL_KEYS, "command")):
        return [_spec_from_config(str(data.get("name") or ""), data, allowed_hosts)]

    raise McpSpecError(
        "I couldn't find a server in that JSON. It should either be "
        '{"mcpServers": {"name": {"url": "..."}}} or just {"url": "..."}.'
    )


def _spec_from_config(name: str, config: Any, allowed_hosts: tuple[str, ...]) -> McpServerSpec:
    label = name or "that server"
    if not isinstance(config, dict):
        raise McpSpecError(f"The config for {label} should be an object.")

    command = config.get("command")
    if command and not _first_url(config):
        # A stdio server is a local subprocess. Running one would mean executing
        # a command a chat message chose, inside the agent's container — and on
        # Cloud Run there is no npx/uvx there to run it with anyway.
        raise McpSpecError(
            f"{label} is a stdio server — it expects me to run `{command}` as a local "
            "process. I can only reach servers over the network, so paste its remote "
            "https URL if it has one."
        )

    url = _first_url(config)
    if not url:
        raise McpSpecError(f'The config for {label} has no "url".')

    declared = str(config.get("type") or config.get("transport") or "").strip().lower()
    if declared and declared not in _TRANSPORTS:
        if declared == "stdio":
            raise McpSpecError(
                f"{label} is declared as a stdio server, which I cannot run. "
                "Paste its remote https URL instead."
            )
        raise McpSpecError(
            f'{label} declares transport "{declared}", which I don\'t know. '
            'Use "http" (streamable HTTP) or "sse".'
        )

    validated = _validate_url(url, allowed_hosts)
    return McpServerSpec(
        name=_slugify(name) if name else _name_from_url(validated),
        url=validated,
        transport=_TRANSPORTS.get(declared) or _transport_from_url(validated),
        headers=_parse_headers(config.get("headers"), label),
    )


def _first_url(config: dict[str, Any]) -> str:
    for key in _URL_KEYS:
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _parse_headers(raw: Any, label: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise McpSpecError(f'"headers" for {label} should be an object of name → value.')
    return {str(key): str(value) for key, value in raw.items()}


def _validate_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise McpSpecError(
            f"`{url}` isn't an http(s) URL, so there's nothing for me to connect to."
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise McpSpecError(f"`{url}` has no hostname.")

    is_local = host in _LOCAL_HOSTS
    if parsed.scheme == "http" and not is_local:
        raise McpSpecError(
            f"`{url}` is plain http. Every request would carry your headers in the "
            "clear, so I only connect over https (localhost aside)."
        )
    if allowed_hosts and not _host_allowed(host, allowed_hosts):
        raise McpSpecError(
            f"`{host}` isn't on this deployment's list of allowed MCP hosts. "
            "An administrator sets that list."
        )
    return url


def _host_allowed(host: str, allowed_hosts: tuple[str, ...]) -> bool:
    for entry in allowed_hosts:
        allowed = entry.strip().lower().lstrip(".")
        if allowed and (host == allowed or host.endswith(f".{allowed}")):
            return True
    return False


def _transport_from_url(url: str) -> str:
    return "sse" if urlparse(url).path.rstrip("/").lower().endswith("/sse") else "http"


def _name_from_url(url: str) -> str:
    """A short prefix for the server's tools, guessed from its hostname.

    `https://mcp.notion.com/mcp` → `notion`: the generic labels and the TLD say
    nothing about which server this is, and the model sees this on every tool.
    """
    labels = [label for label in (urlparse(url).hostname or "").lower().split(".") if label]
    while labels and labels[0] in _GENERIC_LABELS:
        labels.pop(0)
    if len(labels) > 1:
        labels = labels[:-1]
    return _slugify(labels[0]) if labels else "mcp"


def _slugify(raw: str) -> str:
    slug = _NON_SLUG.sub("_", raw.strip().lower()).strip("_")[:_MAX_NAME_LENGTH].strip("_")
    if not slug:
        return "mcp"
    # Gemini tool names must start with a letter, and the prefix leads the name.
    return slug if slug[0].isalpha() else f"mcp_{slug}"


def _deduplicate_names(specs: list[McpServerSpec]) -> list[McpServerSpec]:
    """Keep names unique, since each one becomes a tool-name prefix."""
    seen: set[str] = set()
    result: list[McpServerSpec] = []
    for spec in specs:
        name = spec.name
        suffix = 2
        while name in seen:
            name = f"{spec.name}_{suffix}"
            suffix += 1
        seen.add(name)
        result.append(
            spec if name == spec.name else McpServerSpec(**{**spec.to_dict(), "name": name})
        )
    return result
