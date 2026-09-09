# Working on this repo

An MCP server wrapping imobiliare.ro's AI property search. `README.md` covers
*using* it; this file covers *changing* it — the traps that cost time.

## Layout

```
src/imobiliare_mcp/
  client.py   HTTP against the two upstream hosts; session handling
  parse.py    normalise() raw listing -> typed record; filter_and_rank()
  server.py   MCP tools + the shared Filters model
```

The pipeline is always: **fetch → `normalise` once → `filter_and_rank`**.
Never parse inside a filter predicate or a sort comparator; if you need a new
derived value, add it to `normalise` so it is computed once and everything
downstream can filter and sort on it.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
```

No `uv` on this machine. The system `python3` is a python.org build with **no
CA certificates**, so `urllib` fails TLS verification against these hosts —
that is why the client uses `httpx` (bundles certifi). Don't "simplify" it back
to `urllib`. There is also no `timeout(1)` on macOS; don't use it in test
scripts.

## Testing

`@mcp.tool()` on **MCP SDK 2.x returns the plain function**, so tests call the
tool directly — `cauta(query=...)`, not `cauta.fn(...)`. (SDK 1.x wrapped it in
an object with `.fn`; this is 2.x, where `FastMCP` was also renamed
`MCPServer`.)

Test against `reia` and `detalii`, which need no session. Keep a known-good
`resume_token` around: tokens outlive their session indefinitely, so one saved
token gives you a stable 240-listing fixture to develop filters against.

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'src')
import logging; logging.disable(logging.INFO)   # httpx logs every request at INFO
from imobiliare_mcp.server import reia, Filters
print(reia(token=open('token.txt').read().strip(),
           filtre=Filters(camere=3, pret_max=220000))['matched'])"
```

Smoke-test the stdio protocol after touching `server.py`:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"p","version":"1"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | .venv/bin/imobiliare-mcp
```

## Data invariants — the expensive ones

**Never trust `tracking.ga4Item.price`.** It carries a `0.2` placeholder on
roughly 7% of listings (16 of 240 sampled) — a 215.000 € flat reports as `0.2`.
The *displayed* price string is authoritative; ga4 is a fallback only, guarded
by a plausibility floor. Getting this wrong makes `pret_max` silently admit
garbage rather than fail loudly.

The rest of `ga4Item` is good and is where most filters come from: `sellerType`
(`agency`/`individual`/`developer`), `propertyArea`, `propertyCity`,
`propertyDaysInMarket`, `propertyYear`, `item_category4` (`new`/`established`).

**A missing value fails a constraint.** A listing whose price could not be
parsed must not survive `pret_max=220000` — it has not been shown to satisfy
it. Same for sorting: missing sorts last, never first (`_or_inf`).

**Everything upstream is a display string** — `"108.000 €"` (`.` is a thousands
separator), `"405 m (5 min)"`, `"Etaj 2 / 4"`, `"1969 (Finalizată)"`. Formats
can change without warning; `parse.py` is the blast radius. Floors are
normalised to ints: parter `0`, demisol `-1`, mansardă `99`.

Listings can be **duplicated upstream** — the same flat posted twice under
different neighbourhood labels (seen: ids `275969177` and `275969168`). Any
per-area counting is affected. There is no dedup yet.

## Sessions

`cauta` is the only tool needing `IMOBILIARE_SESSION_ID`, and it is the fragile
part:

- Sessions minted via `POST /api/conversation` are rejected by `/api/search`
  with `403`. Only browser-originated sessions work. `sesiune_noua` exists to
  re-check whether that still holds.
- Browser sessions expire in **minutes**.
- A `403` from the AI host means an expired session and must surface as
  `SessionError`, not a raw `httpx` error — `cauta` turns it into a readable
  message.

Result tokens are the workaround: they outlive the session, so `reia` and
`statistici` keep working. Prefer building on tokens over spending sessions.

## Conventions

Tool names and filter fields are **Romanian** (`cauta`, `pret_max`, `camere`),
because the queries and the domain are; internals — code, comments, docstrings
— are **English**. Keep that split.

Adding a filter means three edits: a field on `Filters`, a line in
`Filters.as_kwargs`, and a check in `filter_and_rank`. Range checks go in the
`checks` tuple, booleans in `flags`.

## Scope

Undocumented internal API, no published terms of use. Keep request volume
modest, don't add retry storms, and treat the unauthenticated `hydrate`
endpoint as something that can be closed off without notice. Search *pages* on
the portal are behind a Cloudflare managed challenge — the JSON endpoints are
not, and nothing here should try to defeat that challenge.
