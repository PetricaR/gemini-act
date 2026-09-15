# Structura raportului imobiliar: sample, web, PDF și structura consolidată

Documentul răspunde la trei întrebări: **ce arată fiecare suprafață astăzi**, **unde
diverg**, și **care este structura corectă** după integrarea playbook-ului de negociere.

Suprafețele sunt patru, nu trei — a patra este ușor de uitat pentru că nu se vede în
aplicația web:

| # | Suprafață | Produsă de | Consumată de |
|---|---|---|---|
| 1 | **Sample (demo)** | `api/demo_data.py` — set scris de mână | `/api/audit/demo` → web + PDF |
| 2 | **Web** | `web/src/App.jsx` + 15 componente | browser |
| 3 | **PDF** | `imobiliare/mcp/generator_pdf.py` | descărcare din web, atașament Chat |
| 4 | **Markdown SEV** | `imobiliare/mcp/raport.py` | unealta `evaluare`, atașament Chat |

---

## 1. Ce arată sample-ul (`DEMO_AUDIT_DATA`)

Set de date autentic ca formă, fictiv ca conținut: un penthouse în Aviatiei Park.
30 de chei de nivel superior:

**Identitate:** `id`, `titlu`, `pret_total`, `moneda`, `suprafata_utila`, `camere`,
`etaj`, `an_constructie`, `adresa`, `complex_name`, `dezvoltator`, `constructor`,
`url`, `lat`, `lon`, `imagini`

**Verdict:** `scor_general`, `calificativ_general`, `rezumat_executiv`,
`puncte_forte`, `puncte_slabe`

**Secțiuni de analiză:** `evaluare_anevar`, `audit_electrocasnice`, `audit_exterior`,
`specificatii_dezvoltator`, `audit_targetare`, `recenzii_google`, `locatie`

**Context și încadrare:** `analiza_piata`, `cea_mai_buna_utilizare`, `esg`, `riscuri`,
`costuri_detinere`, `costuri_tranzactionare`, `receptie_checklist`, `metodologie`,
`ipoteze_limitative`

## 2. Ce arată aplicația web

Nouă taburi peste aceleași componente; `Raport complet` le randează pe toate, în ordine.

| Tab | Componente | Citește din date |
|---|---|---|
| Raport complet | toate | — |
| — (mereu vizibil) | `PropertySummary` | `scor_general`, `pret_total`, `suprafata_utila`, `evaluare_anevar`, `rezumat_executiv`, `puncte_forte/slabe`, `imagini` |
| Evaluare ANEVAR | `ValuationMeter`, `ValuationApproaches` | `evaluare_anevar` |
| Locație & facilități | `LocationMap` | `locatie`, `adresa` |
| Defecte & finisaje | `DefectsInspector` | `audit_electrocasnice(_finisaje)` |
| Dotări incluse | `AppliancesCatalog` | `audit_electrocasnice(_finisaje)` |
| Street View & satelit | `ExteriorInspection` | `audit_exterior`, `locatie` |
| Dezvoltator & recenzii | `DeveloperAudit`, `ReviewsSentiment` | `audit_targetare`, `specificatii_dezvoltator`, `recenzii_google` |
| Piață, costuri & riscuri | `MarketAndRisk` | `analiza_piata`, `riscuri`, `costuri_detinere`, `costuri_tranzactionare`, `esg`, `cea_mai_buna_utilizare` |
| Metodologie | `HandoverChecklist`, `MethodologyNotes` | `checklist_receptie`, `metodologie`, `ipoteze_limitative` |

## 3. Ce arată PDF-ul

Douăsprezece secțiuni numerotate:

1. Sinteză Executivă & Fișă Tehnică Proprietate
2. Evaluare de Piață ANEVAR (GEV 630) & Abordările Valorii
3. Localizare Urbană & Infrastructură POI (rază 500 m)
4. Audit Exterior & Inspecție 360° Street View
5. Audit Finisaje, Calitate Execuție & Estimare Deficiențe
6. Catalog Electrocasnice & Dotări Incluse
7. Profil Dezvoltator, Constructor & Due Diligence Financiar
8. Reputație Rezidențială & Recenzii Google Maps
9. Contextul Pieței, Costuri de Deținere & Registru de Riscuri
10. Checklist Tehnic pentru Recepție & Verificare Acte
11. Metodologie, Ipoteze Limitative & Surse de Date
12. Concluzie Finală & Strategie de Negociere

## 4. Ce arată raportul markdown (SEV 106 §30.6)

Paisprezece secțiuni, structurate pe conținutul minim al standardului: sinteza,
termenii de referință, identificarea proprietății (+ localizare, + constatări din
fotografii), ipoteze limitative, factori ESG, analiza pieței, cea mai bună utilizare,
abordarea prin comparație (elementele §56, modul de estimare §58, grila, selectarea
concluziei §57, detalierea corecțiilor), abordarea prin venit, abordarea prin cost,
reconcilierea, senzitivitatea, riscurile, verificarea conținutului minim.

Este cel mai riguros dintre cele patru și singurul care își declară explicit
neconformitatea (SEV 106 §30.8).

---

## 5. Problemele găsite

### P1 — Sample-ul și raportul generat aveau forme diferite (cauza divergenței)

Cheile pe care PDF-ul le citește, dar pe care pipeline-ul real **nu le producea
niciodată**:

```
analiza_piata · costuri_detinere · costuri_tranzactionare · esg
cea_mai_buna_utilizare · rezumat_executiv · puncte_forte · puncte_slabe
metodologie · ipoteze_limitative · lat · lon · riscuri
```

Sample-ul le avea pe toate, scrise de mână. Consecința era dublă și asimetrică:
în **web** secțiunile respective rămâneau goale, iar în **PDF** se completau cu valori
implicite — adică raportul generat arăta *complet*, dar cu date inventate.

### P2 — PDF-ul fabrica date pentru secțiunile nemăsurate

Valori emise identic pentru orice proprietate, lângă cifre care erau reale:

| Valoare inventată | Unde |
|---|---|
| `+6,2% / an` variație anuală | tabelul de micro-piață |
| `3,5 luni` timp de expunere | idem |
| `14 proprietăți` ofertă concurentă | idem |
| `Stabilă / Creștere moderată` | tendință de piață |
| clasa energetică `A`, `115.4 kWh/mp/an` | profil ESG |
| `BREEAM Excellent / NZEB` | certificare verde |
| `Conform cod seismic P100-1; absență risc inundație` | risc seismic |
| 3 riscuri generice cu probabilitate și impact | registrul de riscuri |
| `suprafață × 1,5` = întreținere lunară | costuri de deținere |

Aceasta este exact clasa de bug pe care `tests/test_audit_integrity.py` a fost scris
să o prevină; lista lui de termeni interziși nu acoperea însă acești termeni.

### P3 — Lipsea complet stratul de negociere

Toate cele patru suprafețe se opreau la *cât valorează*. Întrebarea *cât ofer și când
mă retrag* apărea doar ca un card în PDF care spunea „începeți de la `val_min`, țintiți
`val_piata`” — un interval de ±5% în jurul estimării, fără ancoră, fără prag de abandon
și fără buget consolidat.

### P4 — Chei cu două nume

`audit_electrocasnice` / `audit_electrocasnice_finisaje`, `checklist_receptie` /
`receptie_checklist`, `audit_targetare` / `targetare_financiar`. Fiecare consumator
face `a || b`. Funcționează, dar fiecare nou renderer trebuie să știe ambele nume.
*Neatins în această iterație — merită un pas separat de normalizare.*

### P5 — `make deploy` era rupt

Ținta indica `./deploy/deploy_cloud_run.sh`, fișier care nu există (scriptul aplicației
este `deploy/deploy.sh`; `deploy_cloud_run.sh` există doar sub `deploy/adk_ui/`).
Aceeași cale greșită era documentată în `CLAUDE.md` și `README.md`. **Reparat.**

### P6 — Cheia defectelor era citită sub alt nume

Auditul de finisaje emite `defecte_si_probleme` — obiecte cu `element_afectat` /
`descriere_defect`. Prima versiune a integrării căuta `defecte_identificate` cu un câmp
`descriere`, deci **pârghiile de negociere nu s-ar fi declanșat niciodată pe un anunț
real**, deși testele pe fraze sintetice treceau. **Reparat** (`_constatari_din_audit`),
cu test pe forma reală.

### P7 — Payload-uri prea mari către model

`evaluare` întorcea planul complet de negociere (trei scripturi + trei checklist-uri,
câțiva KB de text) în contextul modelului la fiecare evaluare, iar adaptorul de dosar
întorcea `date_audit` întreg — zeci de KB. Ambele contraziceau regula pe care adaptorul
o declară în propriul docstring: raportul se atașează, nu se recită. **Reparat:**
`evaluare` întoarce o formă compactă (scara + regula + etichetele), planul complet
rămâne în raport și în unealta dedicată; adaptorul de dosar întoarce lista secțiunilor
disponibile în locul dosarului.

### P8 — Tabelul de comparabile: fără linkuri, cu duplicate și cu o distanță inventată

Trei defecte în aceeași secțiune — cea pe care cumpărătorul o folosește ca să verifice
evaluarea:

- **Fără linkuri.** `_comparabila_dict` trimitea `url`, dar niciunul dintre cele *două*
  tabele din `ValuationMeter.jsx` nu îl randa, iar PDF-ul afișa doar id-ul. Comparabilele
  nu puteau fi deschise și verificate. **Reparat** în ambele tabele web (link + id sub el)
  și în PDF (`<link href>` pe fiecare rând). Raportul markdown le lega deja corect.
- **Duplicate.** `dedupe` rula *după* selecția primelor N, deci un apartament listat de
  două ori consuma două locuri din cele 12 și grila ieșea cu un comparabil mai puțin, fără
  să spună de ce. În plus cheia nu prindea relistarea cu un câmp golit. **Reparat:**
  deduplicare înainte de ranking, a doua trecere pe `(preț, suprafață)` care fuzionează
  doar când câmpurile publicate de ambele coincid, iar supraviețuitorul este înregistrarea
  cu cele mai multe date — nu prima văzută.
- **Distanță inventată.** O distanță nepublicată se afișa ca `< 1 km`. `_comparabila_dict`
  trimite `None` tocmai ca să nu se afirme asta. **Reparat:** „nepublicat”.
- **PDF trunchiat la 6 rânduri** dintr-o grilă de 12, iar o ajustare lipsă se afișa ca
  `0.0%` (adică „nu necesită ajustare”). **Reparat:** toate rândurile, `n/a` pentru ce
  nu s-a calculat.

### P9 — Crash în PDF la evaluare fără procent de ajustare

`f"{ajustare_pct:+.1f}%"` cu `ajustare_pct is None` arunca `TypeError` și pica întreaga
generare a PDF-ului, pentru orice evaluare care raporta marja în euro dar nu și în
procente. Preexistent, descoperit de un test nou. **Reparat.**

### P10 — `reguli_de_aur` și `abandon_recomandat` erau produse și nerandate

Cele 10 reguli de aur ajungeau în payload și nu le citea nimeni. Iar
`abandon_recomandat` nu putea fi niciodată `true`: niciun steag nu afirmă o clasă
seismică sau un litigiu neverificat, deci `any(flag.abandon)` era mereu fals. **Reparat:**
regulile se randează în web și în PDF, iar abandonul are acum o condiție demonstrabilă —
bugetul al cărui plafon cade sub oferta de deschidere.

### P11 — `ruff check .` pica deja pe `main`

160 de erori în `generator_pdf.py` (E501 + importuri nefolosite), independent de
modificările de față. Reduse la 141 ca efect secundar; restul rămâne datorie tehnică.

---

## 6. Structura consolidată

Ordinea de mai jos este cea în care se citește un dosar: *ce e*, *cât valorează*,
*unde stă*, *ce a văzut cineva*, *cine vinde*, *cât costă cu totul*, *ce ofer*.
Stratul nou este blocul 7.

| # | Secțiune | Sursa datelor | PDF | Web | MD |
|---|---|---|---|---|---|
| 1 | Sinteză executivă, scor global, puncte forte/slabe | derivat din secțiunile care au măsurat ceva | ✅ | ✅ | ✅ |
| 2 | Fișă tehnică a proprietății | `parse.normalise` | ✅ | ✅ | ✅ |
| 3 | Evaluare ANEVAR: grilă, abordări, reconciliere, senzitivitate | `anevar.py` | ✅ | ✅ | ✅ |
| 4 | Localizare, POI, accesibilitate | `locatie.py`, `api/imagery.py` | ✅ | ✅ | ✅ |
| 5 | Inspecție vizuală: galerie, Street View, finisaje, defecte, dotări | `viziune.py`, `electrocasnice_finisaje.py` | ✅ | ✅ | ✅ |
| 6 | Dezvoltator, constructor, bonitate, recenzii | `dezvoltator.py`, `targetare.py`, `recenzii_maps.py` | ✅ | ✅ | — |
| **7** | **Strategie de negociere** | **`negociere.py`** | **✅ nou** | **✅ nou** | **✅ nou** |
| 7.1 | Scara de ofertare (listat → estimat → OI → CP → PT → PMA → walk-away) | `construieste_scara` | ✅ | ✅ | ✅ |
| 7.2 | Concesii descrescătoare | `concesii` | ✅ | ✅ | ✅ |
| 7.3 | Profilul vânzătorului și tactica adaptată | `profil_vanzator` | ✅ | ✅ | ✅ |
| 7.4 | Pârghii tehnice (defect → deviz → argument → reducere) | `parghii_din_constatari` | ✅ | ✅ | ✅ |
| 7.5 | Semnale roșii și verificări impuse | `steaguri_rosii` | ✅ | ✅ | — |
| 7.6 | Oferte scrise (proprietar / agent / dezvoltator) | `script_oferta` | — | ✅ | — |
| 7.7 | Verificări tehnice, juridice, structurale | `verificari` | ✅ | ✅ | — |
| **8** | **Buget consolidat** | **`costuri.py`** | **✅ nou** | **✅ nou** | **✅ nou** |
| 9 | Piață, costuri de deținere, ESG, registru de riscuri | `_analiza_piata`, `costuri.py`, steaguri roșii | ✅ | ✅ | ✅ |
| 10 | Metodologie, ipoteze limitative, neconformitate SEV | `raport.py`, `_completeaza_strategie` | ✅ | ✅ | ✅ |

### Regula care ține structura unitară

**O secțiune fără date se declară indisponibilă; nu se completează cu o valoare
plauzibilă.** Fiecare cifră poartă o calificare — `FAPT` / `INFERENȚĂ` / `ESTIMARE` /
`OPINIE` — mapată pe badge-urile de proveniență pe care interfața le avea deja
(`masurat` / `estimat` / `anunt` / `indisponibil`).

---

## 7. Ce s-a preluat din playbook

| Element | Unde a ajuns |
|---|---|
| Scara P_L → V_E → OI → CP → PT → PMA → WAP | `negociere.Scara` |
| Ancorare 6–8% sub valoare / 12–16% sub listare | `Parametri.ancora_*` |
| Concesii descrescătoare 50/30/20 | `negociere.concesii` |
| Marja de negociere pe context (1,5–3,5% … 8–15%) | `negociere.CONTEXTE` |
| 7 arhetipuri de vânzător + tactică + erori | `negociere.PROFILE` |
| Tabelul defect → deviz → argument (7 rânduri) | `negociere.PARGHII` |
| Red flags cu reducere justificată | `negociere.STEAG_*` |
| 3 scripturi de ofertă scrisă | `negociere.SCRIPTURI` |
| Checklist tehnic / juridic / structural | `negociere.VERIFICARI_*` |
| Regula decizională universală | `negociere.regula_decizionala` |
| 15 reguli de aur (condensate în 10) | `negociere.REGULI_DE_AUR` |
| Onorariu notarial OMJ 177/C/2024, TVA 21%, ANCPI 0,15% | `costuri.py` |
| Buget consolidat: preț + taxe + renovare + mobilare + rezervă | `costuri.buget_consolidat` |
| Renovare 350–500 EUR/mp | `costuri.RENOVARE_EUR_MP` |

**Nepreluat, deliberat:** bugetul de 180.000 EUR, profilul familiei, cele 4 scenarii,
studiul de caz Titan și tabelul de prețuri pe micro-zone. Primele sunt parametrii unui
singur cumpărător — bugetul este acum argument de unealtă, nu constantă. Ultimul este
măsurat live din ofertele active (`_analiza_piata`), nu citat dintr-un document.

---

## 8. Ce s-a implementat

**Module noi**
- `src/imobiliare/mcp/negociere.py` — scara, profilul, pârghiile, steagurile, scripturile, verificările
- `src/imobiliare/mcp/costuri.py` — onorarii, taxe, buget consolidat

**Modificate**
- `imobiliare/mcp/server.py` — unealta `strategie_negociere`; `_analiza_piata` (micro-piață măsurată); `_completeaza_strategie` (umple toate secțiunile lipsă ale dosarului); `evaluare` întoarce `piata`, `strategie_negociere`, `buget_consolidat`
- `imobiliare/mcp/generator_pdf.py` — secțiunea de negociere (scară, profil, pârghii, regulă decizională); tabel de buget consolidat; **eliminate toate valorile fabricate** de la P2
- `imobiliare/mcp/raport.py` — secțiunile `13b. Strategia de negociere` și `13c. Bugetul consolidat`
- `api/routes.py` — demo și raportul real trec prin aceeași funcție de completare
- `web/src/components/NegotiationStrategy.jsx` — componentă nouă
- `web/src/components/MarketAndRisk.jsx` — acceptă structura de costuri calculată; indicatorii nemăsurați apar ca „Nedeterminat”, nu ca 0%
- `web/src/App.jsx` — tab nou „Negociere & buget”
- `imobiliare/mcp/agent_tools.py`, `gemini_act/agent/prompts.py` — unealta expusă agentului din Chat
- `Makefile`, `CLAUDE.md`, `README.md` — calea corectă a scriptului de deploy

**Teste** — `tests/test_negociere.py` (25), `tests/test_costuri.py` (11),
`tests/test_audit_integrity.py` (+10): interdicția valorilor fabricate acoperă acum și
noile module, paritatea de structură demo ↔ raport generat este testată, la fel și
conținutul efectiv al PDF-ului și forma reală a datelor de audit. Suita: 592 de teste,
toate trec; `ruff` curat pe tot ce a fost atins.

---

## 9. De verificat înainte de a se baza cineva pe cifre

1. **Constantele fiscale au dată.** TVA 21% (Legea 141/2025, din 2025-08-01), onorariul
   notarial (OMJ 177/C/2024), intabularea 0,15% (Ordinul ANCPI 39/2009). Sunt grupate
   la începutul lui `costuri.py` tocmai ca să poată fi reverificate. O grilă expirată
   care încă se calculează este mai periculoasă decât una care refuză să calculeze.
2. **Grila notarială este reprodusă doar pe pragul documentat** (peste 600.001 lei).
   Sub prag se întoarce o bandă marcată `ESTIMARE`, nu trepte inventate.
3. **Cursul EUR/RON este orientativ** (`costuri.CURS_EUR_RON = 5.0`), nu un curs al zilei.
4. **Strategia nu este consultanță juridică** și nu modifică valoarea estimată — este
   raportată lângă ea, niciodată în ea.


---

## 10. Observații rămase (neatinse)

- **P4 — chei cu două nume** (`audit_electrocasnice` / `audit_electrocasnice_finisaje`
  etc.). Merită un pas separat de normalizare, cu alias-uri păstrate o vreme.
- **`/healthz` întoarce 404 în producție** deși ruta există și răspunde local cu 200 —
  răspunsul vine de la frontend-ul Google, nu de la aplicație. Preexistent; scriptul de
  deploy anunță acel URL la final, deci induce în eroare.
- **Datoria de lint din `generator_pdf.py`**: 160 → 141 erori E501, restul preexistent.
- **Playbook-ul** a fost mutat în `src/imobiliare/mcp/docx/`; `negociere.md`,
  care exista la începutul sesiunii, nu mai era pe disc când am încercat să îl citesc.
