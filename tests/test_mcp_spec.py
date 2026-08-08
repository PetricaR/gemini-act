"""Reading an MCP server out of pasted text, and the rules on what is allowed."""

from __future__ import annotations

import json

import pytest

from gemini_act.mcp.spec import (
    McpServerSpec,
    McpSpecError,
    looks_like_mcp_config,
    parse_mcp_config,
)

# --- what counts as "the user handed me a server" ---


@pytest.mark.parametrize(
    "text",
    [
        "https://mcp.example.com/mcp",
        "https://example.com/mcp",
        "https://example.com/sse",
        "https://example.com/mcp/v1",
        "https://mcp-gateway.example.com/",
        '{"mcpServers": {"acme": {"url": "https://acme.com/mcp"}}}',
        '{"url": "https://acme.com/mcp"}',
        '```json\n{"servers": {"acme": {"url": "https://acme.com/mcp"}}}\n```',
        # Not connectable, but recognised so we can explain why rather than
        # handing `npx` to the model.
        '{"mcpServers": {"local": {"command": "npx", "args": ["-y", "srv"]}}}',
    ],
)
def test_recognises_a_pasted_server(text):
    assert looks_like_mcp_config(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "what's on my calendar today",
        # A link with a question around it is a question about the link.
        "summarise https://mcp.example.com/mcp for me",
        # An ordinary link must still reach the model.
        "https://example.com/blog/post",
        "https://docs.google.com/document/d/abc/edit",
        "{not json at all",
        '{"temperature": 0.5}',
        "",
        "   ",
    ],
)
def test_leaves_ordinary_messages_alone(text):
    assert looks_like_mcp_config(text) is False


# --- parsing ---


def test_parses_a_bare_url_and_names_it_after_the_host():
    (spec,) = parse_mcp_config("https://mcp.notion.com/mcp")
    assert spec == McpServerSpec(name="notion", url="https://mcp.notion.com/mcp", transport="http")


def test_infers_sse_transport_from_the_path():
    (spec,) = parse_mcp_config("https://example.com/sse")
    assert spec.transport == "sse"


def test_strips_a_markdown_fence_and_keeps_headers():
    text = """```json
    {
      "mcpServers": {
        "Acme Corp": {
          "url": "https://acme.example.com/mcp",
          "headers": {"Authorization": "Bearer sk-123"}
        }
      }
    }
    ```"""
    (spec,) = parse_mcp_config(text)
    assert spec.name == "acme_corp"
    assert spec.url == "https://acme.example.com/mcp"
    assert spec.headers == {"Authorization": "Bearer sk-123"}


def test_parses_every_server_in_a_multi_server_config():
    text = json.dumps(
        {
            "mcpServers": {
                "one": {"url": "https://one.example.com/mcp"},
                "two": {"url": "https://two.example.com/sse", "type": "sse"},
            }
        }
    )
    specs = parse_mcp_config(text)
    assert [(spec.name, spec.transport) for spec in specs] == [("one", "http"), ("two", "sse")]


def test_accepts_the_vs_code_servers_key():
    text = json.dumps({"servers": {"acme": {"url": "https://acme.example.com/mcp"}}})
    assert parse_mcp_config(text)[0].name == "acme"


@pytest.mark.parametrize("spelling", ["http", "streamable-http", "streamable_http", "HTTP"])
def test_accepts_the_transport_spellings_clients_actually_write(spelling):
    text = json.dumps({"url": "https://acme.example.com/x", "type": spelling})
    assert parse_mcp_config(text)[0].transport == "http"


def test_keeps_names_unique_because_they_become_tool_prefixes():
    """Two servers slugging to the same name would collide in the tool list."""
    text = json.dumps(
        {
            "mcpServers": {
                "acme corp": {"url": "https://a.example.com/mcp"},
                "acme-corp": {"url": "https://b.example.com/mcp"},
            }
        }
    )
    assert [spec.name for spec in parse_mcp_config(text)] == ["acme_corp", "acme_corp_2"]


def test_name_starts_with_a_letter_for_gemini_tool_names():
    (spec,) = parse_mcp_config("https://127.0.0.1:9000/mcp")
    assert spec.name[0].isalpha()


# --- refusals, each with something the user can act on ---


def test_rejects_a_stdio_server_by_explaining_why():
    text = json.dumps({"mcpServers": {"local": {"command": "npx", "args": ["-y", "srv"]}}})
    with pytest.raises(McpSpecError, match="stdio"):
        parse_mcp_config(text)


def test_rejects_a_stdio_type_declaration():
    text = json.dumps({"url": "https://acme.example.com/mcp", "type": "stdio"})
    with pytest.raises(McpSpecError, match="stdio"):
        parse_mcp_config(text)


def test_rejects_plain_http_because_headers_would_travel_in_the_clear():
    with pytest.raises(McpSpecError, match="https"):
        parse_mcp_config("http://acme.example.com/mcp")


def test_allows_plain_http_on_localhost_for_development():
    (spec,) = parse_mcp_config("http://localhost:8931/mcp")
    assert spec.url == "http://localhost:8931/mcp"


def test_rejects_a_non_http_scheme():
    with pytest.raises(McpSpecError, match="http"):
        parse_mcp_config("ftp://acme.example.com/mcp")


def test_reports_where_the_json_broke():
    with pytest.raises(McpSpecError, match="line 1"):
        parse_mcp_config('{"mcpServers": {"a": }}')


def test_rejects_json_with_no_server_in_it():
    with pytest.raises(McpSpecError, match="mcpServers"):
        parse_mcp_config('{"model": "gemini"}')


def test_rejects_a_config_missing_its_url():
    with pytest.raises(McpSpecError, match="url"):
        parse_mcp_config('{"mcpServers": {"acme": {"headers": {}}}}')


def test_rejects_an_unknown_transport():
    with pytest.raises(McpSpecError, match="websocket"):
        parse_mcp_config('{"url": "https://a.example.com/mcp", "type": "websocket"}')


# --- the deployment allowlist ---


def test_allowlist_accepts_a_listed_host_and_its_subdomains():
    hosts = ("acme.example.com", "trusted.dev")
    assert parse_mcp_config("https://acme.example.com/mcp", allowed_hosts=hosts)
    assert parse_mcp_config("https://mcp.trusted.dev/mcp", allowed_hosts=hosts)


def test_allowlist_rejects_anything_else():
    with pytest.raises(McpSpecError, match="allowed MCP hosts"):
        parse_mcp_config("https://evil.example.com/mcp", allowed_hosts=("acme.example.com",))


def test_allowlist_is_not_fooled_by_a_suffix_that_is_not_a_subdomain():
    with pytest.raises(McpSpecError, match="allowed MCP hosts"):
        parse_mcp_config("https://notacme.example.com/mcp", allowed_hosts=("acme.example.com",))


def test_empty_allowlist_accepts_any_https_host():
    assert parse_mcp_config("https://anything.example.com/mcp", allowed_hosts=())


# --- identity of a connection ---


def test_fingerprint_separates_the_same_url_under_different_credentials():
    """Two users' tokens for one URL must not share an upstream session."""
    base = {"name": "acme", "url": "https://acme.example.com/mcp"}
    ada = McpServerSpec(**base, headers={"Authorization": "Bearer ada"})
    bob = McpServerSpec(**base, headers={"Authorization": "Bearer bob"})
    assert ada.fingerprint != bob.fingerprint
    assert (
        ada.fingerprint
        == McpServerSpec(**base, headers={"Authorization": "Bearer ada"}).fingerprint
    )


def test_fingerprint_does_not_leak_the_token():
    spec = McpServerSpec(name="a", url="https://a.example.com/mcp", headers={"X-Key": "secret"})
    assert "secret" not in spec.fingerprint


def test_round_trips_through_storage():
    spec = McpServerSpec(
        name="acme", url="https://acme.example.com/sse", transport="sse", headers={"A": "b"}
    )
    assert McpServerSpec.from_dict(spec.to_dict()) == spec
