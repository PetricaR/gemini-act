# Bug report — `src/gemini_act/imobiliare_mcp`

**Scope:** all 16 modules (8,754 LOC) of the imobiliare.ro MCP server.
**Date:** 2026-09-12 · **Branch:** `main` (with uncommitted working-tree changes)
**Baseline when reported:** `pytest` → 450 passed. `ruff check` → 32 errors (all E501).

> **Status: all 34 findings fixed** (2026-09-12). `pytest` → **505 passed**,
> `ruff check .` → **clean**, stdio `tools/list` → 16 tools. The findings below
> are kept as written for the record; see *Resolution* at the end for what
> changed and the two further bugs the fixes uncovered.

Findings were verified by execution where marked **[reproduced]**. Everything else is
read from the code and cross-checked against the module it calls into.

---

## Summary

| Severity | Count | Theme |
| --- | --- | --- |
| **P0 — crash** | 5 | Unhandled exceptions on reachable paths; three abort PDF generation entirely |
| **P1 — fabricated data** | 10 | Invented numbers and verdicts presented to the buyer as findings |
| **P2 — silently wrong** | 13 | Wrong results, no error raised |
| **P3 — robustness** | 6 | Cloud Run incompatibility, lint, test gaps |

The dominant theme is **P1**. The in-flight working-tree change is clearly an attempt to
stop fabricating data and mark sections `indisponibil` instead — that intent is right, but
the unavailable path is not wired through the PDF renderer (causing the P0 crashes), and a
larger set of fabrication sites was missed than was fixed. As it stands, the report
generator tells every buyer the property scores **8.7/10, "FOARTE BUN — INVESTIȚIE
SIGURĂ"**, and presents a "validated opportunity with controlled risk", regardless of what
any tool actually found.

---

## P0 — Crashes

### 1. `generator_pdf.py:857` — `UnboundLocalError` kills every report with an unavailable valuation
**[reproduced]**

`val_min` / `val_piata` are bound only inside the `else` branch that runs when
`evaluare_anevar.status == "disponibil"`, but the closing negotiation card at line 857
formats them unconditionally:

```python
f"Recomandăm începerea negocierii de la <b>{val_min:,.0f} {moneda}</b>, "
f"cu limită superioară la <b>{val_piata:,.0f} {moneda}</b>. "
```

Any report where the valuation is unavailable — the exact payload [server.py:1045](src/gemini_act/imobiliare_mcp/server.py#L1045) now writes when fewer than 3 comparables qualify, and the one at [server.py:1062](src/gemini_act/imobiliare_mcp/server.py#L1062) written on *any* `evaluare()` exception — raises and produces no PDF at all.

```
UnboundLocalError: cannot access local variable 'val_min' where it is not associated with a value
```

The newly added "indisponibil" branch is therefore unreachable in practice: it is exactly the input that crashes the renderer.

### 2. `generator_pdf.py:409` — `TypeError` on a null adjustment
**[reproduced]**

```python
ajustare_pct = eval_anevar.get("ajustare_recomandata_procent", 0.0)
...
accent_anevar = GOOGLE_GREEN if ajustare_pct >= -3.0 else GOOGLE_AMBER
```

`ajustare_recomandata_procent` can legitimately be `None` ([server.py:1032](src/gemini_act/imobiliare_mcp/server.py#L1032) assigns `dif_pct`, which stays `None` when the asking price or the estimate is missing). `dict.get(key, default)` does **not** substitute for a key that is present and null, so the comparison runs against `None`:

```
TypeError: '>=' not supported between instances of 'NoneType' and 'float'
```

### 3. `server.py:803` — `MapsPlace` has no `formatted_address`
**[reproduced]**

```python
place = maps.geocode(address)
if place:
    lat, lon = place.lat, place.lon
    address = place.formatted_address or address   # AttributeError
```

[maps.MapsPlace](src/gemini_act/imobiliare_mcp/maps.py#L88) defines `lat, lon, display, precision, place_id, location_type`. There is no `formatted_address`; the field is called `display`.

This line is **not** inside a `try`. `analizeaza_strada_si_imprejurimi_street_view` therefore crashes outright whenever it is given an address rather than a listing id or coordinates — the primary documented use of its own first parameter (*"Address (e.g. 'Calea Floreasca 160, Bucuresti')"*). Inside `genereaza_raport_complet_pdf` the same call *is* wrapped, so there the failure is invisible: the exterior audit silently becomes `indisponibil` for every address-based report.

### 4. `server.py:997` — `contact_sheet` called with the wrong signature
**[reproduced]**

```python
cale_gal = contact_sheet(sub)
```

[galerie.contact_sheet](src/gemini_act/imobiliare_mcp/galerie.py#L24) is `contact_sheet(urls: list[str], destination: Path, columns: int = 3, ...)` — two required positional arguments, the first a list of URLs, not a subject dict.

```
TypeError: contact_sheet() missing 1 required positional argument: 'destination'
```

Swallowed by the `except Exception` at line 1000, so the PDF report **never** contains a photo gallery. Contrast [server.py:454](src/gemini_act/imobiliare_mcp/server.py#L454), which calls it correctly.

### 5. `anevar.py:501` — `ZeroDivisionError` on user-supplied weights
**[reproduced]**

```python
v.final_value = (sum(x * w for x, w in zip(parts, weights, strict=True)) / sum(weights)) if parts else None
```

`ParametriEvaluare` declares both `pondere_piata` and `pondere_venit` with `ge=0`, so `{"pondere_piata": 0, "pondere_venit": 0}` is a valid tool input and reaches `sum(weights) == 0`. Nothing validates that the two weights are positive or that they sum to 100 — `{50, 90}` is also accepted and silently renormalised.

---

## P1 — Fabricated data presented as findings

This is the most serious class here, because the output is a document a buyer uses to
decide on a six-figure purchase. Each item below produces a confident-sounding number or
verdict that is not derived from any observation.

### 6. `server.py:1220` — every property scores 8.7/10, "SAFE INVESTMENT"

```python
date_proprietate["scor_general"] = date_proprietate.get("scor_general") or 8.7
date_proprietate["calificativ_general"] = (
    date_proprietate.get("calificativ_general") or "FOARTE BUN - INVESTIȚIE SIGURĂ"
)
```

Nothing upstream ever sets `scor_general`. This is the headline verdict of the report and it is a constant — identical for a renovated new build and for a derelict flat with no valuation, no reviews, no financials and no street view.

### 7. `generator_pdf.py:855` — unconditional closing recommendation

```python
concluzie_text = (
    f"Proprietatea prezintă o oportunitate validată cu risc controlat. ..."
)
```

*"The property presents a validated opportunity with controlled risk"* is emitted for every property, including ones where every section came back `indisponibil`. Nothing about it is conditional on a finding.

### 8. `server.py:969-988` — invented subject facts

```python
date_proprietate["pret_total"]      = sub.get("price_eur")   or r_item.get("price")   or 136488
date_proprietate["suprafata_utila"] = sub.get("surface_sqm") or r_item.get("surface") or 75.2
date_proprietate["camere"]          = sub.get("rooms") or 3
date_proprietate["etaj"]            = ... else "Etaj 1 din 3"
date_proprietate["an_constructie"]  = sub.get("year_built") or 2025
loc_txt = ... or "Theodor Pallady, Sector 3, București"
```

These constants were removed from the `setdefault` block in the working-tree change but left in the hydration assignments. The invented `75.2` mp is then multiplied into `interval_valoare_min` / `interval_valoare_max` / `pret_pe_mp_estimat` at [server.py:1016-1018](src/gemini_act/imobiliare_mcp/server.py#L1016) — i.e. it manufactures an *ANEVAR valuation interval* from a made-up surface.

`tests/test_audit_integrity.py` greps only for the CUI/company strings, so it passes regardless.

### 9. `targetare.py:216` — a company with no financial data scores 7.0 / "financially stable"

```python
ca = date_firma.get("cifra_afaceri") or 0
profit = date_firma.get("profit_net") or 0
...
scor = 7.0
if profit > 0 and marja_profit > 10: scor += 1.5
if profit < 0:                        scor -= 2.5
...
```

`or 0` collapses *missing* into *zero*. A developer with no published financials takes none of the adjustment branches, so `scor_final == 7.0` → `"Moderat (Stabil financiar)"`. The absence of data is reported as evidence of stability.

The same `7.0` default is hard-coded in three more places where a *missing* score is rendered as a real one:

- [generator_pdf.py:726](src/gemini_act/imobiliare_mcp/generator_pdf.py#L726) `analiza_f.get("scor_sanatate_financiara", 7.0)`, plus `nivel_risc_insolventa` defaulting to `"Moderat"`
- [generator_pdf.py:786](src/gemini_act/imobiliare_mcp/generator_pdf.py#L786) `analiza_r.get("scor_reputatie", 7.0)`
- [recenzii_maps.py:322](src/gemini_act/imobiliare_mcp/recenzii_maps.py#L322) same

### 10. `recenzii_maps.py:162` — `"apa"` matches `"apartament"`, inventing a water-damage red flag
**[reproduced]**

```python
if any(k in text_unificat for k in ["infiltratii", "infiltrații", "apa", "igrasie", "mucegai"]):
    probleme.append("Probleme de hidroizolație, umezeală sau infiltrații semnalate")
```

`"apa"` is a substring of `"apartament"` — the single most common word in Romanian property reviews. Verified:

> Input review: *"Apartament superb, totul impecabil, recomand cu încredere!"* (rating 4.8)
> Output: `probleme_reclamate_frecvent → ['Probleme de hidroizolație, umezeală sau infiltrații semnalate']`

An unambiguously positive review produces a structural red flag.

### 11. `server.py:1206` — the "generic" handover checklist names specific products

```python
"Garanții scrise pentru tâmplărie Salamander tripan și centrala termică în condensare",
"Certificat de Performanță Energetică (Clasa A obligatorie la autentificare)",
```

Salamander triple glazing, a condensing boiler and energy class A are asserted for every property, new or old. Class A is also not legally mandatory at authentication.

### 12. `server.py:559` — a missing metro distance becomes 500 m

```python
"distanta_km": round(((... ).get("metro_distance_m") or 500) / 1000, 2),
```

### 13. `anevar.py:283` — a missing metro distance becomes a real grid adjustment
**[reproduced]**

```python
def metro_penalty(rec):
    d = rec.get("metro_distance_m")
    if d is None:
        return p.metro_discount_max_pct / 2     # as if it were 750 m away
```

This is not just a display default — it enters the comparison grid as a `Correction` with basis text citing GEV 630, and it inflates `gross_pct` (the disqualification metric) for the well-documented comparables it is measured against. Verified output for a comparable with no metro data:

```
Distanță până la metrou  1.87  | ? m față de 400 m
```

An adjustment whose own note says the input is `?` contradicts GEV 630 §58, which the module docstring cites as requiring that no adjustment be used without showing how it was estimated.

### 14. `electrocasnice_finisaje.py:626` — confidence inferred from photo count

```python
if not date_finale.get("incredere"):
    date_finale["incredere"] = "ridicata" if len(photos) >= 5 else "medie"
```

When the model declines to state a confidence, the code asserts "high" on photo count alone — contradicting the prompt's own rule that 3D renders or fewer than 5 useful photos imply `"scazuta"`, and driving a high-confidence badge in the UI.

### 15. `generator_pdf.py:400` — invented valuation interval

```python
val_max = eval_anevar.get("interval_valoare_max") or round(val_piata * 1.05)
```

A ±5% band is synthesised and rendered as *"interval rezonabil"* from the ANEVAR comparison grid.

---

## P2 — Silently wrong results

### 16. `server.py:1117` — exterior audit reads a key that does not exist

```python
date_proprietate["audit_exterior"] = ext_res.get("analiza_vizuala_gemini", {})
date_proprietate["audit_exterior"]["status"] = "disponibil"
date_proprietate["audit_exterior"]["disponibil"] = True
date_proprietate["audit_exterior"]["provenienta"] = "model"
```

[viziune_strada.analyse_street_and_surroundings](src/gemini_act/imobiliare_mcp/viziune_strada.py#L438) returns the analysis under `"audit"`, not `"analiza_vizuala_gemini"`. The result is always `{}` — and the next three lines then stamp that empty dict as available, measured and model-sourced. This **permanently suppresses** the `indisponibil` fallback at line 1125 and renders an "available" exterior audit consisting entirely of N/A.

### 17. `comps.py:139` — the least documented comparable ranks first
**[reproduced]**

`rank_by_similarity` accumulates a distance only for fields present on *both* subject and comparable. A record missing `year_built`, `floor` and `metro_distance_m` contributes nothing for those terms, so it scores *lower* (= more similar) than a well-documented near-twin:

```
subject: 60mp, 2000, floor 2, 400m
ranking (best first): ['NO-DATA-AT-ALL', 'well-documented', 'documented-but-older']
```

`evaluare` takes the top *N* of this ranking straight into the GEV 630 grid, so the grid is systematically biased toward the listings carrying the least evidence. This also directly contradicts the documented invariant in `AGENTS.md`: *"missing sorts last, never first (`_or_inf`)"*.

### 18. `anevar.py:335` — a ground-floor adjustment cites the top-floor evidence
**[reproduced]**

```python
src = (rates.ground_floor if (comp.get("floor") or 1) <= 0 else rates.top_floor)
```

The classic falsy-zero bug: for a *parter* comparable `floor == 0`, so `0 or 1` → `1`, `1 <= 0` is False, and `rates.top_floor` is selected. Verified — a comparable at floor 0 reports basis `"TOP-EVIDENCE, n=10"`. The number applied is correct (`floor_penalty` handles 0 properly); only the GEV 630 §58 justification text printed in the report is wrong, which is precisely the part a reviewer would check.

### 19. `server.py:989` — every non-Bucharest address gains ", București"

```python
if "Bucure" not in loc_txt:
    loc_txt += ", București"
```

A property in Cluj, Timișoara or Brașov is relabelled as being in Bucharest. That address then drives geocoding, Street View and the reviews query.

### 20. `server.py:1131` — interior photos presented as street imagery

```python
"imagini_salvate": (date_proprietate.get("imagini") or [])[:2],
```

When the exterior audit is unavailable, the first two *listing interior photos* are placed in the exterior section's `imagini_salvate`, and the PDF renders them under the Street View / facade heading.

### 21. `electrocasnice_finisaje.py:628` — a failed Gemini call returns `status: "success"`

```python
except Exception as exc:
    logger.exception(...)
    fallback_data = _analiza_reguli_fallback(subject)
    return {"status": "success", "mod_analiza": "fallback_eroare_gemini", ...}
```

The project's own `CLAUDE.md` states: *"Always return a dict with a `status` key — the system prompt tells the agent to trust it to tell success from failure, never to report a failed action as successful."* This returns `success` for a path whose own `mod_analiza` is literally `fallback_eroare_gemini`. [server.py:1074](src/gemini_act/imobiliare_mcp/server.py#L1074) gates on `status == "success"`, so keyword-matching guesswork is accepted and labelled `provenienta: "anunt"` in a section presented as a vision audit.

### 22. `server.py:424` — the insufficient-comparables branch returns the wrong record shape

The `< 3` early return puts raw `normalise()` records under `"comparabile"`, while the success path at [server.py:549](src/gemini_act/imobiliare_mcp/server.py#L549) returns re-shaped dicts (`adresa`, `pret`, `suprafata`, `pret_mp`). `ValuationMeter.jsx` renders the list using the re-shaped field names, so the "comparabile identificate" table comes out blank in exactly the case where the user most needs to see what *was* found.

### 23. `server.py:1056` — one canned reason for every failure mode

```python
"motiv": (eval_res or {}).get("motiv") or "Eșantion insuficient: sub 3 comparabile reale identificate..."
```

`evaluare()`'s early error returns at lines 398, 403 and 410 carry no `motiv`, so *listing not found*, *zone not derivable from URL* and *no comparables in the area* all surface to the user as "insufficient sample: fewer than 3 comparables" — three different problems with three different fixes, reported identically.

### 24. `generator_pdf.py:712` — `indisponibil` silently drops sections and desynchronises headings

The Targetare and Google-reviews sections gate on `status == "success"`, but the new payloads use `status == "indisponibil"` / `"disponibil"`. Those two sections therefore vanish entirely — no "unavailable" card, unlike the sections that were updated — and because the headings are hard-coded strings, the numbering jumps **4 → 7**.

### 25. `client.py:168` — "best-effort, never fatal" is not

```python
try:
    raw = self._post(spec["url"], {"token": spec["token"]})
except httpx.HTTPError:
    return {}
```

`_post` raises `SessionError` (a `RuntimeError`) on 403 — the single most common failure mode per `AGENTS.md` ("browser sessions expire in minutes"). It is not an `httpx.HTTPError`, so it escapes and takes down the whole `cauta` call, despite the docstring's *"Best-effort: never fatal."* `r.json()` can also raise `json.JSONDecodeError`, likewise uncaught.

### 26. `recenzii_maps.py:161` — diacritics mismatch drops real complaints
**[reproduced]**

Review text is only `.lower()`-ed, never diacritic-stripped, while the keyword lists mix stripped and unstripped forms. Against the realistic text *"întârziere la predare, infiltrații în baie"*:

| keyword | matches? |
| --- | --- |
| `intarziere` | ✗ |
| `întârziat` | ✗ (text has the noun *întârziere*, list has the participle) |
| `infiltratii` | ✗ |
| `infiltrații` | ✓ |

A genuine delay complaint written with diacritics is missed by both delay keywords. Combined with #10, the fallback analyser is close to inverted: it invents problems that aren't there and misses ones that are.

### 27. `anevar.py:377` — the negotiation margin inflates the disqualification metric

```python
out.gross_eur = sum(abs(c.eur) for c in out.corrections) + pct_as_eur
out.gross_pct = out.gross_eur / price * 100
out.disqualified = out.gross_pct > p.disqualify_gross_pct
```

The negotiation margin (3–12%, applied *identically to every comparable* as a market-conditions normalisation) is counted as a gross adjustment. GEV 630 §57's disqualification threshold is meant to measure how *dissimilar* a comparable is; a universal correction should not consume 3–12% of a 35% budget. Long-listed comparables are disproportionately disqualified. Separately, `pct_as_eur` is computed on `base_per_sqm * surface` (post-negotiation, post-lump-sum) but divided by the original asking `price` — two different bases in one ratio.

### 28. `server.py:562` — net adjustment reported as total adjustment

```python
"ajustare_neta_procent":   round(getattr(c, "net_pct", ...), 1),
"ajustare_totala_procent": round(getattr(c, "net_pct", ...), 1),
```

Both read `net_pct`. `AdjustedComp` carries a distinct `gross_pct`, which is what "total" means in GEV 630 §57 — the two differ whenever corrections have opposite signs, which is the normal case.

---

## P3 — Robustness and environment

### 29. Cache directories assume a writable `$HOME` — breaks on Cloud Run

```python
comps.py:26    CACHE_DIR = Path.home() / ".cache" / "imobiliare-mcp"
locatie.py:31  CACHE_DIR = Path.home() / ".cache" / "imobiliare-mcp" / "geo"
```

Both call `CACHE_DIR.mkdir(parents=True, exist_ok=True)` unconditionally. The codebase already knows this is wrong — [server.py:_reports_dir](src/gemini_act/imobiliare_mcp/server.py#L348) documents it precisely: *"Cloud Run's filesystem is read-only apart from /tmp, and `Path.home()` there is not writable"*. `comps._fetch_cached` is on the critical path of `evaluare`, so this is an `OSError: Read-only file system` in production, not a degraded cache.

### 30. Two more writes outside `/tmp`

- [generator_pdf.py:292](src/gemini_act/imobiliare_mcp/generator_pdf.py#L292) — `rep_dir = Path("reports")`, relative to the process CWD (`/app` on Cloud Run).
- [viziune_strada.py:324](src/gemini_act/imobiliare_mcp/viziune_strada.py#L324) — `target_dir = Path(save_dir) if save_dir else Path.cwd()`.

Neither routes through `_reports_dir()`.

### 31. `parse.py:269` — floor exclusions keep listings with unknown floors

```python
if exclude_ground_floor and r["floor"] is not None and r["floor"] <= 0:
    return False
```

`AGENTS.md` states the invariant plainly: *"A missing value fails a constraint. A listing whose price could not be parsed must not survive `pret_max=220000` — it has not been shown to satisfy it."* The `checks` tuple honours this; `exclude_ground_floor` and `exclude_top_floor` do not, so `fara_parter=True` returns listings that may well be ground floor. Either behaviour is defensible, but it should match the documented rule or the docs should carve out the exception.

### 32. `server.py:790` — broad `except` hides real errors, and a dead branch

The listing-resolution block in `analizeaza_strada_si_imprejurimi_street_view` is wrapped in `except Exception: pass`, which also swallows genuine network and hydration failures. Within it:

```python
elif sub.get("latitude") and sub.get("longitude"):
```

`normalise()` never emits `latitude` / `longitude` keys, so this branch is unreachable. `server.py` contains 15 `except Exception` blocks, most of which `pass` or `logger.debug` — several of the bugs above (#3, #4, #16) are invisible in production precisely because of them.

### 33. Lint: 32 E501 violations

All line-too-long against the configured limit of 100, concentrated in `generator_pdf.py` and `server.py`. `make lint` does not currently pass on this directory.

### 34. No tests for four modules

| module | tests |
| --- | --- |
| `parse.py` | **none** |
| `comps.py` | **none** |
| `client.py` | **none** |
| `galerie.py` | **none** |

`parse.py` is described in `AGENTS.md` as "the blast radius" for upstream format changes, and `comps.py` selects the comparables the entire valuation rests on. Both are pure functions over dicts — cheap to test, and #17 in particular would have been caught by a three-line test.

---

## Suggested order of work

1. **Unblock the PDF** — #1, #2. Without these the working-tree change's own `indisponibil` path cannot produce a document.
2. **Stop the fabrication** — #6, #7, #8, #9. These are four small deletions that change what the report claims more than anything else on this list.
3. **Fix the silent key/signature mismatches** — #16, #3, #4. Each is a one-line fix that restores a whole section of the report.
4. **Correct the grid** — #17, #13, #18, #27. These change the number the report exists to produce.
5. **Then** the environment and hygiene items (#29–#34).

A cheap structural guard for the whole P1 class: have `genereaza_raport_complet_pdf` assert
that no rendered field carries `provenienta == "indisponibil"` while also carrying a
numeric score, and extend `tests/test_audit_integrity.py` beyond its current CUI/company
string grep to assert that a fully-empty `date_proprietate` yields a PDF containing no
score, no verdict and no currency figure.


---

## Resolution (2026-09-12)

All 34 findings are fixed. `pytest` → **505 passed** (450 before, plus 55 new),
`ruff check .` → clean repo-wide, and the stdio smoke test still advertises all
16 tools.

### Two further bugs the fixes uncovered

**A. `dezvoltator.extract_developer_and_constructor_info` invented the developer.**
Found while wrapping the long lines at `dezvoltator.py:1137-1143`. Every field
carried a fabricated `or` default — and three (`zidarie`, `garantie`,
`termen_finalizare`) were unconditional. It named **"Habitat Group Estate"** and
**"Habitat Construct & Development"** as the developer and contractor of *any*
listing that did not identify one, plus concrete class C25/30, Porotherm 25cm
brick, EPS 80 insulation, Salamander joinery, energy class A and a 2025
completion date.

This is worse than #11, because `server.py` feeds `dev_name` straight into the
**Targetare solvency lookup** and the **Google reviews query**. The dossier
therefore ran a real financial due-diligence section, with a real CUI and real
balance-sheet figures, against a company with no connection to the property.

**B. The same fabrication in the PDF renderer.** `generator_pdf.py:722-728` used
`.get("structura_rezistenta", "Cadre beton armat")` and four siblings. Fixing (A)
turned those values into `None`, which `.get(key, default)` does not cover, and
reportlab raised `AttributeError: 'NoneType' object has no attribute 'split'` —
the same present-but-null bug as #2. Both now render "Nespecificat în anunț", or
an unavailable card when nothing at all is known.

### Notable decisions

- **A new `paths.py`** centralises the writable-directory logic that
  `server._reports_dir()` already documented. `comps`, `locatie`,
  `generator_pdf` and `viziune_strada` now route through it, and a read-only
  filesystem degrades (uncached fetch, unsaved images) instead of raising.
- **The headline verdict is now derived.** `server._scor_general()` computes a
  weighted score from the sections that actually produced a measurement, and
  returns `None` with "INDISPONIBIL - date insuficiente pentru un scor global"
  when none did. The PDF's closing recommendation follows it rather than opening
  with "oportunitate validată" unconditionally.
- **Gross adjustment excludes the negotiation margin** (#27). `Correction` gained
  a `normalisation` flag: a correction applied identically to every comparable
  brings them onto a common basis and is not evidence of dissimilarity, so it no
  longer consumes a third of the GEV 630 §57 disqualification budget. `gross_pct`
  is also now expressed against the normalised price the percentages were applied
  to, rather than the asking price.
- **Section numbering is computed** (#24) via a running counter, so a section that
  turns out to be unavailable renders an explanatory card and the headings stay
  consecutive.
- **Two existing tests encoded finding #21** — they asserted
  `status == "success"` on the no-photos fallback. Their *content* assertions
  (nothing invented) were right and are kept; only the status assertion changed.

### Tests added (55)

| File | Covers |
| --- | --- |
| `tests/test_parse.py` (14) | ga4 `0.2` placeholder, thousands separator, floor normalisation, and the "missing value fails a constraint" invariant including the fixed floor exclusions |
| `tests/test_comps.py` (8) | Slug parsing, county→sitemap scope, and #17 — a documented comparable must outrank an undocumented one |
| `tests/test_client.py` (12) | `SessionError` on 403, the best-effort explanations fetch (#25), string-keyed explanations, id chunking, payload shapes |
| `tests/test_galerie.py` (6) | Contact-sheet tiling, directory creation, and partial/total download failure |
| `tests/test_audit_integrity.py` (+15) | The fabrication guard: a source grep (comments and docstrings stripped via `ast`) for values that can never be legitimate, behaviour tests that missing data yields no score, and a parametrised check that the PDF generates for every "unavailable" combination |

The fabrication guard is deliberately split: a source grep for the handful of
strings that are never legitimate (`"FOARTE BUN - INVESTIȚIE SIGURĂ"`,
`"Habitat Group Estate"`, `136488`, `"Theodor Pallady"`), and behaviour tests for
everything else. Brand names like Salamander and Porotherm legitimately appear in
the model prompts that ask Gemini to *recognise* such brands, so grepping for
those would have been a false-positive generator.
