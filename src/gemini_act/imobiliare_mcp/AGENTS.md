# Working on this repo

An MCP server wrapping imobiliare.ro's AI property search. `README.md` covers
*using* it; this file covers *changing* it — the traps that cost time.

## Layout

```
src/imobiliare_mcp/
  client.py   HTTP against the two upstream hosts; session handling
  imo360.py   the second source: session-free, geographic, carries rentals
  imoradar.py the third source: an aggregator over every major RO portal
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

## The second listings source (`imo360.py`)

`admin.imo360.ro/v1/market/explorer` — unauthenticated, nationwide, and the
only source here that carries **rentals**, which is what makes a gross yield
computable. It selects geographically (bounding box or zone id) rather than
textually, and `/zones` publishes the gazetteer behind that: 1588 zones, ~450
with real polygons. `normalise()` emits the same record shape `parse.py` does,
so `filter_and_rank`, the comparables grid and the report renderer all work on
these records unchanged — which also means **every key that layer subscripts
must be present**, as `None` when this source doesn't publish it. An absent key
is a `KeyError`, not a constraint that fails.

The traps, in the order they cost time:

- **The `sale` index is not only sales.** Sorted by price ascending, the first
  page for Gheorgheni (Cluj) is a 600 € "sale", an ad whose own title says *de
  inchiriat*, one priced in RON, and two sales of a *cotă ideală* — a 21%
  undivided share. They land exactly where they do the most damage: the bottom
  of a price sort, and the p25 of any distribution. `_suspect()` flags them and
  every statistic excludes them; nothing deletes them, because the ad is real.
- **~39% of a page can be the same property twice.** Measured: 200 listings
  from `Titanul Nou` collapse to 122 on (price, surface, rooms, address).
  Worse here than on the imobiliare.ro side because these records feed medians
  *and* a published supply count. `dedupe()` runs before anything averages.
  What it cannot fix is the upstream `total`, which is inflated by the same
  duplication — so that number is the market's *listing* count, not its
  property count, and saying otherwise overstates supply.
- **`usableArea` is missing about half the time; `totalArea` never is.** They
  differ by roughly 15-20%, so a price per sqm is not comparable across
  listings without knowing which was used. `surface_basis` records it, and
  `market_snapshot` forces *one* basis across both sides of a yield — letting
  each side pick its own was producing yields off by the built-to-usable ratio.
- **Don't sample by score.** The default ordering is the vendor's own score; a
  median of the top 300 of 711 listings by score is a median of the good ones.
  `market_snapshot` samples newest-first and reports `sample.complete` so a
  caller can tell a whole-market figure from a sampled one.
- **`total` saturates at 10000** and says so via `totalIsCapped`. Above it the
  number means "at least", and `SearchPage.supply` returns `None` rather than
  let a cap be reported as a count. Filters pushed server-side are what bring
  it back under the cap.
- **The `title` is the source ad's headline and is regularly wrong about the
  location** — listing 5194980 is titled "zona Carpati 1 - Satu Mare" and sits
  in Sector 1, București. Trust `latitude`/`longitude`/`zone`/`locality`/
  `region`; the title is display text.
- **Prices are not all in EUR.** A few are `"ron"`. There is no FX rate in this
  codebase, so `price_eur` is set only for EUR and the raw pair is kept.
- Multiple `zoneIds` **do** work as a union (109 + 3889 = 3998, checked). A
  name like "Militari" resolves to two zones in two sectors and both are kept
  — dropping one silently halves the market being measured.
- Zones without a polygon publish a **degenerate bbox** (the same point four
  times). Passing that to a bbox search matches nothing, so `_zone()` reports
  it as no bbox and the caller uses the zone id instead.

The vendor's score block (`total`, `grade`, and the value/yield/liquidity/
appreciation/location/negotiation/condition/appeal/trust sub-scores) is kept
under `imo360_score`, deliberately *not* merged into the record: an ANEVAR
valuation has to be derivable from comparables and stated adjustments, and an
opaque vendor score is evidence to weigh beside it, never an input to it.

## The aggregator source (`imoradar.py`)

`imoradar24.ro` is not a fourth portal, it is an index **over** the others —
one result page for Titan carried ads sourced from `Imobiliare.ro`,
`storia.ro`, `olx.ro`, `publi24.ro`, `homezz.ro`, `LaJumate.ro` and
`anuntul.ro`. Two things follow, and they are the whole reason it is here:

- It reaches the **`proprietar` segment**, which lives on OLX and Publi24 and
  which nothing else here indexes. 16.592 of the 136.751 apartments on sale
  nationwide; on an owners-only search of Militari the breakdown was publi24
  29, olx 26, storia 20, imobiliare.ro 4.
- Where a property is advertised more than once, **every ad comes back with
  its own price**, seller and posting date in `sellerSources`.

It runs the *same platform as imobiliare.ro* — identical `price` display
strings, `highlights`, `extraFeatures`, `metroDistance` and `tracking.ga4Item`
— so `parse.normalise` does the base work verbatim and `imoradar.normalise`
only overrides what this source means differently. That is also why
`parse.normalise` grew a `base_url`: same parser, different host.

Transport: the site is an **Inertia** app. The same URL answers with ~1,5 MB of
HTML carrying the payload in `data-page`, or with ~360 KB of JSON alone given a
matching `X-Inertia-Version` — a stale version is a bare `409`. So the JSON
route is used whenever a version is known and the HTML route is both the
fallback and where the version comes from; a deploy upstream costs one extra
request, not an outage.

The traps, in the order they cost time:

- **`propertyDaysInMarket` is days since *imoradar24 indexed the ad*, not days
  on the market.** Listing 2287996 reports 2 days while its own Imobiliare.ro
  ad says 06-03-2026 — six months earlier. But the reverse also happens:
  listing 2249080 had been in the index 6 days while the oldest ad still
  standing was 3 days old, because the ad that brought it in was gone. Neither
  number is a ceiling, so `days_on_market` is the **longer** of the two and
  means "on the market at least this long". Freshness is the signal a
  negotiation turns on; an error there has to fall in this direction.
- **A price spread is only evidence when it is between different sellers.**
  Listing 2147878 carries four prices, 175.450 → 193.479 € (10,3%), all posted
  the same day by one agent — a project's several units grouped as one
  property. Listing 2249080's 144.900 vs 149.900 € is two agencies on one
  property, which is the real thing. `price_spread_scope` separates them and
  `negociere.py` may only argue from `cross_seller`.
- **`ga4Item.sellerType` speaks Romanian** (`proprietar`) while
  `sellerSources[].sellerType` in the same payload speaks the vocabulary
  everything here filters on (`individual`). Unmapped, `tip_vanzator=
  "individual"` matches nothing at all on this source.
- **The owner segment carries prices no sale could be at** — 4 of 213 (1,9%):
  266 € for a garsonieră, 476 € for a 62 mp flat, both monthly rents filed as
  sale prices. None at all in the agency-fed pool. Flagged by `_suspect` and
  dropped from the tool's results by default, exactly as `cauta_imo360` does
  it. Unlike imo360 there is **no title check to add**: this portal rewrites
  every heading into its own house style, so an advertiser writing *de
  inchiriat* never survives into `title`.
- **Expired ads are served among live results** — 2 of 150, with `isArchived`
  false and the card rendering normally. Flagged (`expired`), not dropped: an
  expired ad is still evidence of an asking price.
- **`address` falls back to the neighbourhood** and repeats `location`
  verbatim when the seller published no street. This portal has no `Locație
  exactă` badge for `parse.normalise` to find, so `exact_location` is derived
  from the two actually differing, and `address_text` is cleared when they do
  not — otherwise a geocoder reports a street-level fix it never had. Only
  3-8% of listings carry a street.
- The ga4 **`0.2` price placeholder is here too**, on ~9% (8 of 90) — the same
  rate as imobiliare.ro, guarded by the same code.

### Asking-price history (`price_history`, `summarise_history`)

`/api/portal/listings/{id}/price-history` returns what the asking price has
done since the portal first saw the property — the strongest negotiation input
in this package, and the reason `istoric_pret_imoradar` exists. 68% of sampled
listings have one (184 of 270), and the endpoint answers for the rest too,
with a single point.

It is under `/api/`, which robots.txt disallows. **Fetching it is a deliberate
decision, taken explicitly, not an oversight** — so keep it the way it was
scoped: one listing at a time, on a user's explicit request, through
`throttle` like everything else, and never as a sweep across a result set. If
that posture ever needs revisiting, this paragraph is the thing to re-read.

Reading the series is where it goes wrong quietly:

- **A point is a range across the ads standing that day, not one price.** 9 of
  37 sampled points had `minPrice != maxPrice`. When several agencies
  advertise one flat, the range closes as the dearest ad ends: listing 2103212
  reads `154.000-178.500`, `154.000-178.500`, `154.000` — which is an ad
  ending, not a 13,7% concession. A point yields a price only when it is
  unambiguous, and `change_pct` is computed only between two such points.
  `ambiguous_points` says how much of the history could not be read.
- **A zero is a missing value.** 7 of 37 points (19%) carried `minPrice: 0`
  against a real `maxPrice` — listing 2226030 opens `(0, 125000)`. Taken as a
  price that is a 100% collapse, in the one tool a buyer would act on. With it
  read as missing, the same listing reports −8,0%, which its own
  `priceChange.oldPrice` (124.990 €) independently confirms.
- **An empty `data` is not a stable price.** An id that does not exist answers
  `200` with `{"data": []}`, exactly like a listing that was never tracked.
  `observed: False` covers both and must never be worded as "unchanged" — the
  tool's `nota` says so in as many words, because this is the one error here
  that would actively mislead a negotiation.
- **`first_seen` beats every other age signal.** It reaches back a year on old
  stock (listing 1686071: first seen 23.09.2025, still advertised 355 days
  later), past both `postedOn` and this portal's indexing date.
- Dates are `DD.MM.YYYY` — dots, where `sellerSources[].postedOn` in the same
  payload uses dashes. Same portal, two formats. Prices arrive as ints and as
  floats (`180449.72`), and duplicate dates are normal: three observations on
  `10.08.2026` is one property re-checked, not bad data.

### Everything else about the request pattern

`robots.txt` shapes the rest, and it is not incidental: it disallows **every**
query-string filter, then allows exactly `?page=2` … `?page=10`. So searching
goes through the canonical path URLs
(`/apartamente-de-vanzare/bucuresti/sector-3/titan/3-camere/proprietar`), the
gazetteer of 2.367 such locations is built from the published
`sitemap-category-ro.xml` rather than from the disallowed autocomplete
endpoint, and `MAX_PAGES` is 10. The other `/api/portal/...` endpoints the
page uses (alerts, contact forms, phone reveals) are not touched.

## The seismic register (`risc_seismic.py`)

Not a listings source at all: the AMCCRS register of Bucharest buildings with
a seismic risk classification, looked up by street address
(`verifica_risc_seismic`). Full notes are in that module's docstring; the two
that bite first:

- The page at `amccrs-pmb.ro/lista-imobile-2/` contains **no table**. It is a
  Ninja Tables widget that loads its 2.796 rows from `admin-ajax.php` after
  render, so parsing the HTML finds an empty `<colgroup>`. The AJAX URL is
  scraped out of the widget's inline config rather than hard-coded, so a new
  table id upstream is followed rather than breaking the tool.
- **Every column is hand-typed free text** spanning decades. The risk class
  arrives in a dozen spellings and the urgency category (U1–U3) lives in
  `observatii`, not in the class column. Word order is load-bearing:
  `INCADRARE IN CATEGORIE DE URGENTA; NEINCADRATE IN CLASE DE RISC` and
  `NEINCADRAT IN CATEGORIA DE URGENTA SAU CLASE DE RISC` contain the same two
  words and mean opposite things — matching on containment rather than on the
  leading word silently reclassifies 143 buildings as urgent.

The one behaviour not to "simplify": **absence from the register is not a
clean bill of health.** It lists buildings that have *been expertised*, so an
un-expertised 1930s block is missing for the worse reason. Every result carries
that caveat, and the prompt repeats it, because "not on the list" otherwise
reads to a buyer as reassurance.

`constatare()` is what the reports consume, and it separates three states that
a valuation has to word differently: **not asked** (`None` — no address, a
neighbourhood label like "Zona Universitate" rather than a street, or the
register was unreachable), **asked and absent**, and **asked and classified**.
Only a match at building level is `concludent`; a street-level one is reported
as an outstanding check, because the neighbour's *bulina rosie* is not this
flat's. It feeds `raport.render` (special assumption 4 and the ESG table),
`negociere.steaguri_rosii` (a `FAPT` flag replacing the year-of-construction
"check is due" one, `abandon=True` only for RsI) and the PDF's ESG row. None of
them touches the valuation *number* — the class is reported as a fact and
argued in the negotiation, not folded into the GEV 630 grid.

## Reference documents from Drive (`drive_docs.py`)

A Google Drive folder, read-only, holding the paperwork a valuation leans on
but cannot derive: cost catalogues, ANEVAR guidance, developer spec sheets.
`docx/` is the same idea checked into the repo; this is the version that
updates by dropping a file in Drive. Three MCP tools sit on it —
`documente_drive` (list), `citeste_document_drive` (read one, paged through
`de_la`/`urmatorul_offset`), `cauta_in_documente_drive` (grep the corpus for a
passage instead of loading whole PDFs into the context).

**A Drive scope does not survive ADC, and it fails silently.**
`google.auth.default(scopes=[...])` applies scopes only to credentials that can
be re-scoped. A developer's ADC is an `authorized_user` whose scopes are fixed
in the refresh token at login — the default `gcloud auth application-default
login` has no Drive scope, and the requested one is dropped without a word. Fix:

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive.readonly
```

On Cloud Run the same hole has a different floor: the metadata server issues a
`cloud-platform` token, which does not cover Drive, and a service's scopes
cannot be changed. So `_credentiale_drive` self-impersonates through the IAM
Credentials API, which *can* mint `drive.readonly` for a service account. That
is the default rather than a setting, because the alternative is a service that
works locally and 403s in production. It needs
`roles/iam.serviceAccountTokenCreator` on the account for itself —
`deploy/setup_gcp.sh` grants it. `IMOBILIARE_DRIVE_IMPERSONATE` forces the same
path locally, which is how you reproduce the deployed behaviour.

**The quota project decides which project must have `drive.googleapis.com`
enabled**, and ADC carries whatever `gcloud` last set — on a machine that works
on several projects, routinely an unrelated one. `_credentiale_drive` pins it to
`GOOGLE_CLOUD_PROJECT`; without that the 403 names a project nobody here has
heard of.

**Drive access is not IAM.** No role on the GCP project grants it. The folder
has to be *shared* with the identity the process runs as — ADC, so on Cloud Run
the runtime service account from `deploy/setup_gcp.sh` — exactly the way it
would be shared with a colleague. Until it is, Drive reports the folder as
**404 Not Found**, never 403, so "wrong folder id" is the expected symptom of a
folder nobody ever shared. `_indisponibil` names the principal that needs the
share rather than quoting the raw error, and `identitate()` is what reads it
off the live credentials.

Two follow-on traps from the same fact: a service account belongs to no
Workspace domain, so a domain that blocks external sharing refuses that share
(fix: a Shared Drive with the account as a member, or domain-wide delegation),
and it has no Drive storage quota of its own, which is why nothing here copies
or converts server-side.

Listing a folder on a **Shared Drive** needs both `supportsAllDrives` and
`includeItemsFromAllDrives`. Without them the call succeeds and returns zero
files — indistinguishable from an empty folder, and it will not raise.

**A scanned PDF must not extract as `""`.** Pages of images with no text layer
are the normal state of half the documents anyone uploads, and an empty string
reads downstream as an empty document rather than as a document that needs OCR.
`_text_pdf` raises with the page count instead. Same rule as the missing-value
invariant above. `tests/test_drive_docs.py` builds its PDFs with reportlab and
reads them back with pypdf precisely so this path is exercised for real.

The extracted text is cached under `paths.cache_dir("drive")` keyed by the
file's `modifiedTime`, so a re-upload invalidates its own entry and no TTL can
be wrong; the listing itself carries a short TTL (`LISTING_TTL`) so a turn that
lists then reads three documents pays one round trip, not four.

## The PDF dossier (`generator_pdf.py`)

**The report cannot use the standard PDF fonts.** Helvetica & co. are Type1
with WinAnsi encoding — Latin-1 — which has `â` and `î` but not `ă` (U+0103),
`ș` (U+0219) or `ț` (U+021B). Every heading, table cell and paragraph of a
Romanian valuation report drew those three as black boxes. `fonts/` therefore
ships the Roboto family (Apache-2.0) and `_register_fonts()` embeds it; the
deploy image is `python:3.12-slim`, which has no fonts at all, so discovering
one on the system is not an option. If registration ever fails the module falls
back to Helvetica and logs a warning — the report still renders, badly.

Two consequences to keep in mind when editing:

- **Every string bound for a `Paragraph` goes through `_txt()`.** Most of the
  prose is model-generated or scraped, so it can carry anything; `_txt` maps
  the decorative glyphs Roboto lacks (`★ ✓ → ⚠`) onto ones it has, normalises
  `ş/ţ` (cedilla — the wrong letters for Romanian) to `ș/ț`, and drops the
  rest. Reach for a symbol only after checking it is in the font.
- **Images are fitted, never sized.** `Image(path, width=W, height=H)` stretches
  to exactly W×H; listing photos and 4:3 Street View captures were both being
  squashed. Use `_imagine_incadrata(path, max_w, max_h)`.

The other recurring bug class here is **a key the payload never emits**, which
`or` chains turn into a plausible-looking default rather than a visible gap:
`venit_net_anual_eur` read as `venit_net_anual_noi_eur` printed `0 EUR/an`
under a real rent, and `calitate` read as `nivel_calitate` graded every finish
"Medie" next to a score of 9,2. When adding a row, check the key against
`api/demo_data.py` and prefer a dash over a flattering default — a fallback
that asserts a finding ("Trotuare pietonale conforme") is worse than an empty
cell, because nobody inspected those trotuare.

Also watch the **two percentages that mean opposite things**: the correction
recommended against the asking price (`ajustare_recomandata_procent`, negative
when the flat is dear) and the excess of the asking price over the estimate
(`ecart_pct`, computed locally, positive for the same flat). Printing one under
the other's label produced "cu −4,9% peste nivelul pieței".

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
