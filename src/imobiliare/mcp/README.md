# imobiliare_mcp

An MCP server for the Romanian residential property market: listing search across four
sources, a valuation under the Romanian standards (SEV 2025 / GEV 630), due-diligence
audits over photographs, Street View, the seismic register and developer financials, and a
PDF dossier that pulls all of it together. 28 tools.

It runs as a local stdio server for a desktop client, as a streamable-HTTP server, or
in-process as a plain Python library — the same tool functions, three ways in.

> Changing this server rather than using it? Read [AGENTS.md](AGENTS.md) instead: the data
> invariants there are the ones that cost time to rediscover.

## Quick start

```bash
uv sync                      # or: python3 -m venv .venv && .venv/bin/pip install -e .

imobiliare-mcp               # stdio — what a desktop client launches
imobiliare-mcp --list-tools  # the catalogue, with the server's own instructions
```

`--list-tools` starts no server and needs no configuration, so it is the fastest check
that an install works. Add `--json` for the machine-readable form.

### Connect it to Claude Code

```bash
claude mcp add imobiliare -- imobiliare-mcp
```

### Connect it to Claude Desktop

In `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "imobiliare": {
      "command": "imobiliare-mcp",
      "env": {
        "GOOGLE_CLOUD_PROJECT": "your-project",
        "GEMINI_ACT_MAPS_API_KEY": "your-maps-key"
      }
    }
  }
}
```

Use an absolute path to the binary (`.venv/bin/imobiliare-mcp`) if the client does not
inherit your shell's `PATH` — most do not.

### Over HTTP

```bash
imobiliare-mcp --transport streamable-http --port 8081
```

Loopback-bound with DNS-rebinding protection on, stateless, at `http://127.0.0.1:8081/mcp`.
`--host 0.0.0.0 --allow-remote` opens that up and should only be done behind a proxy that
authenticates.

For a **deployed** HTTP endpoint, use `imobiliare-http` rather than this flag: it is the
same server mounted inside the FastAPI app in [`../app.py`](../app.py), which adds the
bearer-token gate (`IMOBILIARE_MCP_TOKEN`), the Cloud Run host handling and the report UI.
`make deploy-imobiliare` deploys it.

## Tools

`RO` read-only · `W` writes · `W!` writes and overwrites a caller-chosen path, so a client
should confirm first. Every tool is annotated on the wire with these hints, plus
`openWorldHint` — false only for `imobiliare_build_handover_checklist`, the one tool that
answers entirely from data shipped in the package.

### Searching

The four search tools are not interchangeable; this is the single most useful thing to
know about the server.

| Tool | | What it is for |
| --- | --- | --- |
| `imobiliare_search_listings` | RO | imobiliare.ro's own AI search. Best relevance, but needs a browser-captured session that expires in minutes. Falls back to the headless route by itself. |
| `imobiliare_search_listings_headless` | RO | The same site with no credential at all. |
| `imobiliare_search_imo360` | RO | Nationwide, unauthenticated, geographic rather than textual — and the only source carrying **rentals**, so the only one that makes a yield computable. |
| `imobiliare_search_imoradar` | RO | An aggregator over imobiliare.ro, storia.ro, olx.ro and publi24.ro at once — so the only one reaching **owner-posted** stock. |
| `imobiliare_resume_search` | RO | Re-filter an earlier search from its `resume_token`. Tokens outlive the session that made them, so this is cheaper than searching again. |
| `imobiliare_get_listings` | RO | Full details for specific listing ids. Needs no session. |
| `imobiliare_get_market_stats` | RO | Price distribution and breakdown by area, seller and age for a result set. |
| `imobiliare_get_market_pulse` | RO | Both sides of one zone — sale and rent — and the gross yield between them. |
| `imobiliare_get_imo360_listing` | RO | One imo360 listing, with its whole photo gallery. |
| `imobiliare_get_price_history` | RO | What a listing's asking price has done since the portal first saw it. The strongest negotiation input here. |
| `imobiliare_create_session` | W | Mints a session id. Of limited use — see the tool's own description. |

### Valuing and negotiating

| Tool | | What it is for |
| --- | --- | --- |
| `imobiliare_appraise_property` | W! | One apartment valued under SEV 2025 / GEV 630: comparables grid, location and amenities, a vision pass over the photographs, written to a markdown report. |
| `imobiliare_plan_negotiation` | RO | That valuation turned into an offer ladder, a read of the counterparty and a walk-away. |
| `imobiliare_generate_pdf_report` | W! | Orchestrates the audits below into one PDF dossier. The most expensive call here. |

### Due diligence

| Tool | | What it is for |
| --- | --- | --- |
| `imobiliare_inspect_photos` | RO | Ask an arbitrary question of the listing photographs. |
| `imobiliare_analyze_furnishings` | RO | Furniture and finishes, from the photographs. |
| `imobiliare_analyze_defects` | RO | Appliances and finish defects, with repair costs. |
| `imobiliare_analyze_build_materials` | RO | Construction materials and technical specs of a new build. |
| `imobiliare_analyze_developer` | RO | The developer's and the contractor's track record. |
| `imobiliare_check_developer_solvency` | RO | Financial due diligence on a developer, by CUI or name. |
| `imobiliare_analyze_street_view` | RO | The street and surroundings from 360° Street View, optionally satellite. |
| `imobiliare_check_seismic_risk` | RO | A Bucharest building against the AMCCRS register (*bulină roșie*). Absence from the register is **not** a clean bill of health — the result says so, and so should you. |
| `imobiliare_get_maps_reviews` | RO | Google Maps reviews for a complex, showroom or address. |
| `imobiliare_build_handover_checklist` | RO | A stage-appropriate reception checklist for a new build, including the Law 10/1995 warranties. |

### Reference documents

A read-only Google Drive folder holding the paperwork a valuation leans on but cannot
derive — cost catalogues, ANEVAR guidance, developer spec sheets.

| Tool | | What it is for |
| --- | --- | --- |
| `imobiliare_list_documents` | RO | What is in the folder. Start here. |
| `imobiliare_read_document` | RO | One document's text, paged. |
| `imobiliare_ask_document` | RO | A question put to a document with the model reading its pages — the right one when the answer lives in a table or a figure. |
| `imobiliare_search_documents` | RO | Find the passage without loading whole PDFs. |

## Configuration

Everything is environment-driven. **Nothing is required**: with an empty environment the
imo360, imoradar and headless imobiliare.ro searches, the comparables grid and the seismic
register all work. Each variable below buys back one capability.

| Variable | Buys |
| --- | --- |
| `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | The Gemini vision passes — every `analyze`/`inspect` tool, and the visual section of the valuation. |
| `GEMINI_ACT_MAPS_API_KEY` | Geocoding, amenities, travel times, Street View and the location map. Without it the valuation degrades to OpenStreetMap: free, coarser and much slower. |
| `GEMINI_ACT_MAPS_AMENITY_RADIUS_M` | Radius of the amenity search (default 1200). |
| `IMOBILIARE_SESSION_ID` *(or `GEMINI_ACT_IMOBILIARE_SESSION_ID`)* | `imobiliare_search_listings`. Captured from DevTools → Network → `/api/search`; expires within minutes, which is why nothing important depends on it. |
| `IMOBILIARE_DRIVE_FOLDER_ID` | The four document tools. The folder must also be **shared** with the identity the process runs as — no IAM role grants Drive. |
| `IMOBILIARE_DRIVE_IMPERSONATE` | Forces the self-impersonation path locally, reproducing Cloud Run's behaviour. |
| `IMOBILIARE_DRIVE_MAX_PAGINI_OCR` | Page ceiling for transcribing a scanned PDF (default 30). |
| `GEMINI_ACT_TARGETARE_API_KEY` *(or `TARGETARE_API_KEY`)* | `imobiliare_check_developer_solvency`. |
| `OBSCURA_BIN` | The headless browser behind `imobiliare_search_listings_headless`; `make install-obscura` puts it where this expects. |
| `GEMINI_ACT_IMOBILIARE_ENABLED`, `GEMINI_ACT_IMO360_ENABLED`, `GEMINI_ACT_IMORADAR_ENABLED` | Per-source switches, all on by default. |
| `GEMINI_ACT_IMOBILIARE_COMPARABLES` | Comparables carried into the GEV 630 grid (default 12). |
| `GEMINI_ACT_IMOBILIARE_MAX_PHOTOS` | Photographs sent to the vision model per listing (default 24). |
| `GEMINI_ACT_IMOBILIARE_VISION_ENABLED`, `GEMINI_ACT_IMOBILIARE_VISION_MODEL` | Turn the vision passes off, or pin the model. |
| `IMOBILIARE_CACHE_DIR`, `IMOBILIARE_REPORTS_DIR` | Where the sitemap/geo caches and the generated reports go. |
| `IMOBILIARE_MCP_TOKEN`, `IMOBILIARE_MCP_HOSTS` | Read by the deployed HTTP service only, not by this command. |

See [`../config.py`](../config.py) for the reasoning behind each default.

## How the server behaves

**Failures are tool errors, not results.** A tool that cannot do its job raises, and the
client sees `isError: true` with the reason — an expired session names the three tools that
need no credential, an unresolvable id says what a listing id looks like. A dict reporting
`status: "error"` would come back as `isError: false`, which reads to a model as success,
so nothing here does that. Unexpected exceptions are logged with their traceback
server-side and reach the caller as type and message only.

**Results are structured.** Every tool publishes an `outputSchema` and returns
`structuredContent` alongside the text.

**Nothing blocks the server.** The tool bodies are synchronous and an appraisal spends
minutes in them, so each call runs on a worker thread. One long valuation does not stall
other clients.

**Conventions in every result.** Prices in EUR; surfaces in usable sqm; floors as integers
(*parter* 0, *demisol* −1, *mansardă* 99); a listing id is the trailing number of an
imobiliare.ro offer URL. A missing value is `null` and never counts as satisfying a filter.

**Protocol.** Built on the MCP Python SDK (`mcp >= 1.29`), which speaks up to
`2025-11-25` and negotiates down. The legacy SSE transport is available behind
`--transport sse` but is deprecated by the specification — prefer streamable HTTP.

## Security

- **Tool annotations are hints, not a boundary.** `readOnlyHint` describes intent; it does
  not stop anything. Two tools take a caller-chosen output path and overwrite it, and both
  declare `destructiveHint` so a client can ask first.
- **HTTP is loopback-only by default**, with `Origin`/`Host` validation on. These tools
  read a configured Drive folder and spend a Maps key, so an open port is a real exposure.
  The deployed service additionally requires a bearer token and fails *closed* when it is
  unset.
- **These are undocumented upstream APIs** with no published terms of use. Keep request
  volume modest and add no retry storms. `imobiliare_get_price_history` reads a path
  `robots.txt` disallows: it is deliberate, scoped to one listing on explicit request, and
  must not become a sweep across a result set.
- **Model output is data.** What a vision pass or a document says is evidence to weigh,
  never an instruction to follow.
