"""What `imobiliare_mcp` publishes, checked as a client would read it.

The tools themselves are tested module by module (`test_comps.py`,
`test_imo360.py`, ...). This file tests the *surface*: the contract an MCP
client sees before it calls anything, and the two properties of the
registration wrapper that nothing else would catch if they broke —

* the registered callable is `async`, so a minutes-long appraisal runs on a
  worker thread instead of stalling every other client of the server;
* the module-level Python name is still the plain function, because
  `imobiliare/agent_tools/` imports and calls these directly, in process.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest
from mcp.types import Tool

from imobiliare.mcp import app, cli, server
from imobiliare.mcp.app import ToolError, _as_tool_error, _guarded
from imobiliare.mcp.client import SessionError

NAME_RE = re.compile(r"^imobiliare_[a-z0-9]+(_[a-z0-9]+)*$")


@pytest.fixture(scope="module")
def tools() -> list[Tool]:
    assert server.mcp is app.mcp  # importing server is what registers them
    return asyncio.run(app.mcp.list_tools())


# --- the server itself ---------------------------------------------------


def test_server_is_named_for_the_service_it_integrates():
    """`{service}_mcp`, the convention a client's server list is read under."""
    assert app.SERVER_NAME == "imobiliare_mcp"
    assert app.mcp.name == "imobiliare_mcp"


def test_the_server_explains_itself_before_any_tool_is_called():
    assert app.mcp.instructions
    assert len(app.mcp.instructions) > 500


def test_every_tool_the_instructions_name_actually_exists(tools):
    """A worked example that references a tool that is gone is worse than none."""
    published = {t.name for t in tools}
    named = set(re.findall(r"`(imobiliare_\w+)`", app.INSTRUCTIONS))
    assert named, "the instructions should walk through the tools by name"
    assert named <= published, f"instructions name missing tools: {named - published}"


# --- names ---------------------------------------------------------------


def test_names_are_prefixed_snake_case(tools):
    """Prefixed because this server is loaded beside others, and `cauta` or
    `detalii` would collide with anything else offering a search."""
    bad = [t.name for t in tools if not NAME_RE.match(t.name)]
    assert not bad, bad


def test_names_are_unique_and_within_the_length_clients_allow(tools):
    names = [t.name for t in tools]
    assert len(names) == len(set(names))
    assert all(len(n) <= 64 for n in names)


def test_the_whole_catalogue_is_published(tools):
    assert len(tools) == 28


# --- descriptions and annotations ----------------------------------------


def test_every_tool_has_a_title_and_a_description(tools):
    for t in tools:
        assert t.title, f"{t.name} has no human-readable title"
        assert (t.description or "").strip(), f"{t.name} has no description"


def test_every_tool_is_annotated(tools):
    for t in tools:
        assert t.annotations is not None, f"{t.name} is unannotated"
        assert t.annotations.readOnlyHint is not None, t.name
        assert t.annotations.openWorldHint is not None, t.name


def test_read_only_tools_leave_the_write_hints_unset(tools):
    """Per the specification those two are meaningful only when a tool writes;
    asserting defaults for a reader says nothing and invites a wrong reading."""
    for t in tools:
        if t.annotations.readOnlyHint:
            assert t.annotations.destructiveHint is None, t.name
            assert t.annotations.idempotentHint is None, t.name


def test_the_tools_that_write_a_file_say_so(tools):
    """Both take a caller-chosen output path and overwrite it, which is what
    should make a client ask first."""
    writers = {t.name for t in tools if not t.annotations.readOnlyHint}
    assert writers == {
        "imobiliare_appraise_property",
        "imobiliare_generate_pdf_report",
        "imobiliare_create_session",
    }
    by_name = {t.name: t for t in tools}
    for name in ("imobiliare_appraise_property", "imobiliare_generate_pdf_report"):
        assert by_name[name].annotations.destructiveHint is True


def test_the_one_tool_that_touches_nothing_external_says_so(tools):
    """`openWorldHint=False` is only honest for the checklist: every other tool
    here reaches a portal, Maps, Drive or a vision model."""
    closed = {t.name for t in tools if not t.annotations.openWorldHint}
    assert closed == {"imobiliare_build_handover_checklist"}


# --- schemas -------------------------------------------------------------


def test_schemas_survive_the_wire(tools):
    """The wrapper must not cost the schema: FastMCP resolves the postponed
    annotations in `server.py` through `__wrapped__`, and losing that would
    show up here as an unresolved name or an empty parameter list."""
    for t in tools:
        blob = json.dumps(t.model_dump(by_alias=True, exclude_none=True))
        assert t.inputSchema["type"] == "object"
        assert "properties" in t.inputSchema
        assert "$ref" not in blob or "$defs" in blob


def test_a_nested_pydantic_filter_still_reaches_the_client(tools):
    search = next(t for t in tools if t.name == "imobiliare_search_listings")
    props = search.inputSchema["properties"]
    assert set(props) >= {"query", "filtre", "sort", "limit", "pool"}
    assert "Filters" in search.inputSchema["$defs"]
    assert "pret_max" in search.inputSchema["$defs"]["Filters"]["properties"]


def test_results_are_structured(tools):
    for t in tools:
        assert t.outputSchema is not None, f"{t.name} publishes no output schema"


# --- the registration wrapper --------------------------------------------


def test_nothing_blocks_the_event_loop():
    """Every tool underneath is synchronous `httpx`; FastMCP would otherwise
    call it inline and one appraisal would stall the whole server."""
    manager = app.mcp._tool_manager
    blocking = [t.name for t in manager.list_tools() if not t.is_async]
    assert not blocking, blocking


def test_the_python_functions_are_untouched():
    """`agent_tools/imobiliare.py` imports these and calls them directly."""
    for fn in (server.cauta, server.evaluare, server.detalii, server.statistici):
        assert not asyncio.iscoroutinefunction(fn)
    assert server.checklist_receptie_imobil_nou(etapa="antecontract")["etapa_selectata"] == (
        "antecontract"
    )


# --- failures ------------------------------------------------------------


def test_a_failure_is_raised_so_the_client_marks_it_as_one():
    """A dict saying `status: error` returns over MCP as `isError: false`,
    which reads to a model as success."""

    def boom(**_: object) -> dict[str, object]:
        raise SessionError("403 from the AI host")

    with pytest.raises(ToolError) as caught:
        asyncio.run(_guarded("imobiliare_search_listings", boom)())
    assert "403 from the AI host" in str(caught.value)


def test_an_expired_session_names_the_tools_that_work_without_one():
    message = str(_as_tool_error("imobiliare_search_listings", SessionError("expired")))
    assert "imobiliare_search_imo360" in message
    assert "imobiliare_resume_search" in message


def test_a_deliberate_failure_is_relayed_verbatim():
    """These carry messages written to be read; wrapping them adds noise."""

    class DriveIndisponibil(RuntimeError):  # same shape as the real one
        pass

    DriveIndisponibil.__module__ = "imobiliare.mcp.drive_docs"
    err = _as_tool_error("imobiliare_list_documents", DriveIndisponibil("share the folder with X"))
    assert str(err) == "share the folder with X"


def test_a_bad_identifier_is_told_what_an_identifier_looks_like():
    message = str(_as_tool_error("imobiliare_get_listings", ValueError("no such listing")))
    assert "no such listing" in message
    assert "trailing number" in message


def test_an_unexpected_error_reaches_the_caller_without_a_traceback():
    message = str(_as_tool_error("imobiliare_appraise_property", ZeroDivisionError("x")))
    assert message == "ZeroDivisionError: x"


def test_a_tool_error_raised_inside_is_not_wrapped_again():
    def boom(**_: object) -> None:
        raise ToolError("already actionable")

    with pytest.raises(ToolError, match="^already actionable$"):
        asyncio.run(_guarded("t", boom)())


# --- the command ---------------------------------------------------------


def test_the_catalogue_is_machine_readable(capsys):
    cli.main(["--list-tools", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["server"] == "imobiliare_mcp"
    assert len(payload["tools"]) == 28
    assert all(t["name"].startswith("imobiliare_") for t in payload["tools"])


def test_the_catalogue_reads_as_prose_too(capsys):
    cli.main(["--list-tools"])
    out = capsys.readouterr().out
    assert "imobiliare_appraise_property" in out
    assert "[writes, destructive]" in out
    assert "[read-only]" in out


def test_http_is_not_reachable_off_the_box_unless_asked():
    args = cli.build_parser().parse_args([])
    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.allow_remote is False
    assert args.stateful is False
