"""Pre-compiled demo property audit dataset, so the report renders instantly."""

from __future__ import annotations

from typing import Any

DEMO_AUDIT_DATA: dict[str, Any] = {
    "id": "demo-aviatiei-park",
    "titlu": "Penthouse 3 Camere & Terasă Panoromică - Aviatiei Park",
    "pret_total": 345000,
    "moneda": "EUR",
    "suprafata_utila": 118.5,
    "camere": 3,
    "etaj": "Etaj 9 din 10",
    "an_constructie": 2022,
    "adresa": "Soseaua Pipera 4B, Sector 1, București",
    "complex_name": "Aviatiei Park",
    "dezvoltator": "Forte Partners",
    "constructor": "Bog'Art",
    "url": "https://www.imobiliare.ro/oferta/demo-aviatiei-park",
    "scor_general": 8.8,
    "calificativ_general": "EXCELENT - RISC SCĂZUT",
    "imagini": [
        "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=1200&q=80",
        "https://images.unsplash.com/photo-1600566753376-12c8ab7fb75b?auto=format&fit=crop&w=1200&q=80",
    ],
    "evaluare_anevar": {
        "valoare_estimata_piata": 328000,
        "interval_valoare_min": 315000,
        "interval_valoare_max": 342000,
        "pret_pe_mp_estimat": 2768,
        "pret_pe_mp_cerut": 2911,
        "ajustare_recomandata_procent": -4.9,
        "marja_negociere_eur": 17000,
        # Two different quantities, and the report shows both: the asking price
        # sits 5,2% above the estimate, which is a 4,9% correction measured
        # against the asking price. Spelling that out avoids reading the report
        # as if it contradicted itself.
        "verdict_piata": (
            "Ușor supraevaluat față de tranzacțiile recente din complex — corecție "
            "recomandată de −4,9% față de prețul cerut"
        ),
        "fiabilitate": "Ridicată",
        "motiv_fiabilitate": (
            "Trei comparabile în același ansamblu sau la sub 600 m, toate finalizate în "
            "2021-2023, cu ajustări nete sub 5% — dispersia valorilor corectate este de 3,0%."
        ),
        "data_evaluarii": "10.09.2026",
        "moneda": "EUR",
        "tip_valoare": "Valoare de piață (SEV 102)",
        "abordare_venit": {
            "chirie_lunara_estimata_eur": 1450,
            "chirie_mp_eur": 12.2,
            "grad_neocupare_procent": 8.0,
            "cheltuieli_operationale_procent": 18.0,
            "venit_net_anual_eur": 13100,
            "rata_capitalizare_procent": 4.1,
            "valoare_prin_venit_eur": 319500,
            "randament_brut_procent": 5.04,
            "comentariu": (
                "Chirie derivată din 6 oferte active de 3 camere în Aviatiei Park și Cloud 9, "
                "ajustate pentru terasă și etaj superior. Rata de capitalizare este în intervalul "
                "3,9-4,3% observat pe segmentul rezidențial premium din nordul Bucureștiului."
            ),
        },
        "abordare_cost": {
            "valoare_teren_alocata_eur": 74000,
            "cost_reconstructie_nou_eur": 289000,
            "deprecierea_fizica_procent": 6.0,
            "deprecierea_functionala_procent": 0.0,
            "valoare_prin_cost_eur": 335660,
            "comentariu": (
                "Cost de înlocuire 2.100 €/mp construit (structură beton armat, fațadă ventilată, "
                "finisaje premium), cotă indiviză de teren 4,8%. Folosită doar ca test de "
                "verosimilitate, nu ca abordare principală."
            ),
        },
        "reconciliere": {
            "pondere_comparatie_procent": 70,
            "pondere_venit_procent": 25,
            "pondere_cost_procent": 5,
            "concluzie": (
                "Greutatea principală revine abordării prin comparație: piața ansamblului este "
                "activă și există tranzacții recente în aceeași clădire. Abordarea prin venit "
                "confirmă nivelul (319.500 €), iar cea prin cost servește doar ca plafon superior."
            ),
        },
        "senzitivitate": [
            {"scenariu": "Rată de capitalizare 3,9%", "valoare_eur": 335900, "delta_procent": 2.4},
            {"scenariu": "Scenariu de bază", "valoare_eur": 328000, "delta_procent": 0.0},
            {"scenariu": "Rată de capitalizare 4,3%", "valoare_eur": 304700, "delta_procent": -7.1},
            {
                "scenariu": "Corecție de piață -5% pe segment premium",
                "valoare_eur": 311600,
                "delta_procent": -5.0,
            },
        ],
        "comparabile_utilizate": [
            {
                "id": "comp-1",
                "adresa": "Aviatiei Park Corp A, Etaj 7",
                "pret_total": 325000,
                "suprafata_utila": 115.0,
                "pret_mp": 2826,
                "an_constructie": 2022,
                "distanta_km": 0.05,
                "ponderi_ajustare": "+1.5% etaj superior",
                "data_tranzactiei": "aprilie 2026",
                "ajustari": [
                    {"element": "Drepturi de proprietate transmise", "procent": 0.0},
                    {"element": "Condiții de finanțare", "procent": 0.0},
                    {"element": "Condiții de vânzare", "procent": 0.0},
                    {"element": "Condiții de piață (data tranzacției)", "procent": 0.5},
                    {"element": "Localizare", "procent": 0.0},
                    {"element": "Etaj și panoramă", "procent": 1.5},
                    {"element": "Suprafață utilă", "procent": -0.5},
                    {"element": "Finisaje și dotări", "procent": 0.0},
                ],
                "ajustare_neta_procent": 1.5,
                "ajustare_bruta_procent": 2.5,
                "valoare_corectata_eur_mp": 2868,
            },
            {
                "id": "comp-2",
                "adresa": "Cloud 9 Residence, Soseaua Pipera",
                "pret_total": 310000,
                "suprafata_utila": 112.0,
                "pret_mp": 2767,
                "an_constructie": 2021,
                "distanta_km": 0.45,
                "ponderi_ajustare": "+4.0% finisaje superioare Aviatiei",
                "data_tranzactiei": "februarie 2026",
                "ajustari": [
                    {"element": "Drepturi de proprietate transmise", "procent": 0.0},
                    {"element": "Condiții de finanțare", "procent": 0.0},
                    {"element": "Condiții de vânzare", "procent": -1.0},
                    {"element": "Condiții de piață (data tranzacției)", "procent": 1.0},
                    {"element": "Localizare", "procent": 1.5},
                    {"element": "Etaj și panoramă", "procent": 1.0},
                    {"element": "Suprafață utilă", "procent": -0.5},
                    {"element": "Finisaje și dotări", "procent": 2.5},
                ],
                "ajustare_neta_procent": 4.5,
                "ajustare_bruta_procent": 7.5,
                "valoare_corectata_eur_mp": 2892,
            },
            {
                "id": "comp-3",
                "adresa": "Nusco City, Soseaua Pipera",
                "pret_total": 335000,
                "suprafata_utila": 122.0,
                "pret_mp": 2745,
                "an_constructie": 2023,
                "distanta_km": 0.60,
                "ponderi_ajustare": "-2.0% suprafață mai mică",
                "data_tranzactiei": "iunie 2026",
                "ajustari": [
                    {"element": "Drepturi de proprietate transmise", "procent": 0.0},
                    {"element": "Condiții de finanțare", "procent": 0.0},
                    {"element": "Condiții de vânzare", "procent": 0.0},
                    {"element": "Condiții de piață (data tranzacției)", "procent": 0.0},
                    {"element": "Localizare", "procent": 1.0},
                    {"element": "Etaj și panoramă", "procent": 2.0},
                    {"element": "Suprafață utilă", "procent": -2.0},
                    {"element": "Finisaje și dotări", "procent": 0.5},
                ],
                "ajustare_neta_procent": 1.5,
                "ajustare_bruta_procent": 5.5,
                "valoare_corectata_eur_mp": 2786,
            },
        ],
    },
    "audit_electrocasnice": {
        "status": "success",
        "scor_finisaje": 8.8,
        "clasa_finisaje": "Premium",
        "rezumat_audit": (
            "Proprietate cu finisaje de înaltă calitate din clasa Premium. "
            "Pardoseli din parchet triplustratificat din lemn masiv de stejar, "
            "tâmplărie Schuco aluminiu tripan cu izolare acustică excelentă și "
            "obiecte sanitare Villeroy & Boch suspendate cu rezervoare Geberit. "
            "Pachet electrocasnice complet de marcă (Bosch, Miele, Samsung, Daikin)."
        ),
        "total_valoare_nou_eur": 8750,
        "total_valoare_nou_ron": 43750,
        "total_valoare_actuala_eur": 6310,
        "total_valoare_actuala_ron": 31550,
        "buget_total_reparatii_eur": 300,
        "buget_total_reparatii_ron": 1500,
        "levier_negociere_recomandat_eur": 17300,
        "categorii_finisaje": [
            {
                "categorie": "Pardoseli",
                "calitate": "Parchet triplustratificat lemn masiv stejar 14mm",
                "nota": 9.2,
                "observatii": (
                    "Montaj fără praguri inestetice, stare excelentă fără zgârieturi adânci."
                ),
            },
            {
                "categorie": "Tâmplărie ferestre",
                "calitate": "Tâmplărie aluminiu Schuco AWS 75.SI+ cu geam tripan",
                "nota": 9.5,
                "observatii": "Feronerie ascunsă, etanșare fonică superioară spre bulevard.",
            },
            {
                "categorie": "Uși interioare & intrare",
                "calitate": (
                    "Uși filomuro înălțime 2.40m cu balamale ascunse și ușă metalică Dierre"
                ),
                "nota": 9.0,
                "observatii": "Închidere magnetică silențioasă, clanțe premium din inox periat.",
            },
            {
                "categorie": "Obiecte sanitare & băi",
                "calitate": (
                    "Plăci ceramice Marazzi porțelanate, baterii Grohe Essence, Villeroy & Boch"
                ),
                "nota": 8.9,
                "observatii": (
                    "Rigole de duș încastrate în pardoseală, rezervoare WC încastrate Geberit."
                ),
            },
            {
                "categorie": "Instalații termice & climatizare",
                "calitate": "Încălzire în pardoseală Rehau cu termostate smart în fiecare cameră",
                "nota": 9.4,
                "observatii": (
                    "Distribuitoare individuale, sistem climatizare Daikin multi-split cu inverter."
                ),
            },
        ],
        "defecte_identificate": [
            {
                "element": "Îmbinare tavan gips-carton dormitor",
                "defect": (
                    "Micro-fisură superficială de contracție la îmbinarea plăcilor de rigips."
                ),
                "severitate": "Minor",
                "cost_estimat_eur": 150,
                "cost_estimat_ron": 750,
                "remediere": (
                    "Armare cu bandă de fibră de sticlă, spacluire și retuș vopsea lavabilă."
                ),
            },
            {
                "element": "Rigolă duș baie matrimonială",
                "defect": "Garnitură de silicon ușor decolorată la îmbinarea cu faianța.",
                "severitate": "Minor",
                "cost_estimat_eur": 80,
                "cost_estimat_ron": 400,
                "remediere": (
                    "Îndepărtare silicon vechi, degresare și aplicare silicon anti-mucegai."
                ),
            },
            {
                "element": "Plintă parchet zonă balcon",
                "defect": "Plintă din MDF ușor desprinsă pe 40 cm lângă rama ușii exterioare.",
                "severitate": "Minor",
                "cost_estimat_eur": 70,
                "cost_estimat_ron": 350,
                "remediere": "Refixare mecanică / adeziv polimeric și etanșare acrilică fină.",
            },
        ],
        "electrocasnice": [
            {
                "aparat": "Frigider Side-by-Side Twin Cooling",
                "camera": "Bucătărie",
                "brand_detectat": "Samsung",
                "model_sau_serie": "RS68A8840B1",
                "clasa_pret": "Premium",
                "pret_nou_estimat_eur": 1200,
                "pret_nou_estimat_ron": 6000,
                "valoare_actuala_eur": 850,
                "valoare_actuala_ron": 4250,
                "stare": "Foarte bună, uși inox negru impecabile",
                "cautare_emag": "https://www.emag.ro/search/Samsung+RS68A8840B1",
                "cautare_altex": "https://altex.ro/cauta/?q=Samsung+RS68A8840B1",
                "cautare_google": (
                    "https://www.google.com/search?q=Samsung+RS68A8840B1+pret+romania"
                ),
            },
            {
                "aparat": "Cuptor Electric Încorporabil cu Piroliză",
                "camera": "Bucătărie",
                "brand_detectat": "Bosch",
                "model_sau_serie": "Seria 8 HBG6764S1",
                "clasa_pret": "Premium",
                "pret_nou_estimat_eur": 850,
                "pret_nou_estimat_ron": 4250,
                "valoare_actuala_eur": 600,
                "valoare_actuala_ron": 3000,
                "stare": "Excelentă, curățare automată prin piroliză",
                "cautare_emag": "https://www.emag.ro/search/Bosch+Seria+8+HBG6764S1",
                "cautare_altex": "https://altex.ro/cauta/?q=Bosch+Seria+8+HBG6764S1",
                "cautare_google": (
                    "https://www.google.com/search?q=Bosch+Seria+8+HBG6764S1+pret+romania"
                ),
            },
            {
                "aparat": "Plită cu Inducție DirectSelect",
                "camera": "Bucătărie",
                "brand_detectat": "Bosch",
                "model_sau_serie": "PXX675DC1E FlexInduction",
                "clasa_pret": "Premium",
                "pret_nou_estimat_eur": 600,
                "pret_nou_estimat_ron": 3000,
                "valoare_actuala_eur": 420,
                "valoare_actuala_ron": 2100,
                "stare": "Suprafață ceramică fără ciobituri",
                "cautare_emag": "https://www.emag.ro/search/Bosch+PXX675DC1E",
                "cautare_altex": "https://altex.ro/cauta/?q=Bosch+PXX675DC1E",
                "cautare_google": ("https://www.google.com/search?q=Bosch+PXX675DC1E+pret+romania"),
            },
            {
                "aparat": "Mașină de Spălat Vase Încorporabilă",
                "camera": "Bucătărie",
                "brand_detectat": "Bosch",
                "model_sau_serie": "SilencePlus SMV46KX01E",
                "clasa_pret": "Premium",
                "pret_nou_estimat_eur": 700,
                "pret_nou_estimat_ron": 3500,
                "valoare_actuala_eur": 490,
                "valoare_actuala_ron": 2450,
                "stare": "Funcțională, proiecție InfoLight pe podea",
                "cautare_emag": "https://www.emag.ro/search/Bosch+SilencePlus+SMV46KX01E",
                "cautare_altex": "https://altex.ro/cauta/?q=Bosch+SilencePlus+SMV46KX01E",
                "cautare_google": (
                    "https://www.google.com/search?q=Bosch+SilencePlus+SMV46KX01E+pret+romania"
                ),
            },
            {
                "aparat": "Mașină de Spălat Rufe TwinDos",
                "camera": "Spălătorie",
                "brand_detectat": "Miele",
                "model_sau_serie": "W1 WCR860 WPS",
                "clasa_pret": "Ultra-Lux",
                "pret_nou_estimat_eur": 1500,
                "pret_nou_estimat_ron": 7500,
                "valoare_actuala_eur": 1100,
                "valoare_actuala_ron": 5500,
                "stare": "Stare impecabilă, motor cu inducție ProfiEco",
                "cautare_emag": "https://www.emag.ro/search/Miele+W1+WCR860",
                "cautare_altex": "https://altex.ro/cauta/?q=Miele+W1+WCR860",
                "cautare_google": ("https://www.google.com/search?q=Miele+W1+WCR860+pret+romania"),
            },
            {
                "aparat": "Sistem Climatizare Multi-Split Inverter",
                "camera": "Living & Dormitoare",
                "brand_detectat": "Daikin",
                "model_sau_serie": "Stylish R-32 Matt Black",
                "clasa_pret": "Premium",
                "pret_nou_estimat_eur": 2100,
                "pret_nou_estimat_ron": 10500,
                "valoare_actuala_eur": 1600,
                "valoare_actuala_ron": 8000,
                "stare": "3 unități interioare, control prin aplicație Wi-Fi",
                "cautare_emag": "https://www.emag.ro/search/Daikin+Stylish+R32",
                "cautare_altex": "https://altex.ro/cauta/?q=Daikin+Stylish+R32",
                "cautare_google": (
                    "https://www.google.com/search?q=Daikin+Stylish+R32+pret+romania"
                ),
            },
            {
                "aparat": "Smart TV OLED 4K 65 inch",
                "camera": "Living",
                "brand_detectat": "LG",
                "model_sau_serie": "OLED65C31LA",
                "clasa_pret": "Premium",
                "pret_nou_estimat_eur": 1800,
                "pret_nou_estimat_ron": 9000,
                "valoare_actuala_eur": 1250,
                "valoare_actuala_ron": 6250,
                "stare": "Panou fără burn-in, suport de perete ultra-slim Vogel's",
                "cautare_emag": "https://www.emag.ro/search/LG+OLED65C31LA",
                "cautare_altex": "https://altex.ro/cauta/?q=LG+OLED65C31LA",
                "cautare_google": ("https://www.google.com/search?q=LG+OLED65C31LA+pret+romania"),
            },
        ],
    },
    "audit_exterior": {
        "scor_exterior": 9.3,
        "clasa_fatada": "Fațadă ventilată modernă",
        "stare_fatada": (
            "Fațadă ventilată cu plăci ceramice Porcelanosa, fără exfolieri sau infiltrații."
        ),
        "trotuare_si_acces": (
            "Trotuare largi pavate (2.5m lățime), rampe de acces cu înclinație optimă."
        ),
        "cabluri_aeriene": (
            "Cablare 100% subterană în tubulatură dedicată NetCity, fără cabluri aeriene."
        ),
        "parcare_si_strazi": (
            "Acces securizat cu barieră automată și recunoaștere plăcuțe, 2 niveluri subterane."
        ),
        "acoperis_terasa": (
            "Terasă circulabilă cu hidroizolație dublă termosudată și termoizolație PIR 20cm."
        ),
        "imagini_salvate": [
            "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?auto=format&fit=crop&w=1000&q=80",
            "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=1000&q=80",
        ],
    },
    "specificatii_dezvoltator": {
        "dezvoltator": "Forte Partners",
        "constructor": "Bog'Art",
        "regim_inaltime": "2S + P + 10E",
        "structura_rezistenta": (
            "Cadre din beton armat (C30/37) cu stâlpi, diafragme și radier general."
        ),
        "inchideri_pereti": (
            "Cărămidă Porotherm 25cm la exterior, compartimentări Ytong & rigips dublu."
        ),
        "certificare_verde": "BREEAM Excellent & Eficiență Energetică Clasa A (nZEB ready).",
        "termen_finalizare": "Recepționat la termen (Fără întârzieri contractuale)",
    },
    "audit_targetare": {
        "status": "success",
        "cui": "RO33621458",
        "denumire": "FORTE PARTNERS DEVELOPMENT S.R.L.",
        "an_infiintare": 2014,
        "stare": "FUNCȚIUNE / ACTIV",
        "cifra_afaceri_ron": 145820000,
        "profit_net_ron": 24150000,
        "datorii_totale_ron": 42100000,
        "numar_angajati": 48,
        "capitaluri_proprii_ron": 98600000,
        "grad_indatorare": 0.29,
        "scor_bonitate": 9.2,
        "calificativ_risc": "Risc Minim de Insolvență (A+)",
        "alerta_spv": (
            "Companie corporativă solidă cu portofoliu mixt, nu este SPV de unică folosință."
        ),
    },
    "recenzii_google": {
        "status": "success",
        "rating_mediu": 4.6,
        "numar_recenzii": 142,
        "puncte_forte": [
            "Parc privat generos de 11.000 mp amenajat superb între corpuri.",
            "Izolație fonică foarte bună între apartamente datorită pereților fonoabsorbanți.",
            "Finisaje comune de lux (marmură, 2 lifturi Schindler rapide per scară).",
            "Serviciu de pază permanentă 24/7 și mentenanță rapidă.",
        ],
        "probleme_recurente": [
            "Trafic intens la orele de vârf pe Șoseaua Pipera către pasajul Barbu Văcărescu.",
            "Costuri lunare de administrare mai ridicate din cauza întreținerii parcului privat.",
        ],
    },
    # --- Report-level chapters, mirroring the SEV 106 §30.6 structure that
    # `imobiliare_mcp/raport.py` renders in Markdown. The web report shows the
    # same material; nothing here is display-only filler.
    "rezumat_executiv": (
        "Penthouse de 118,5 mp utili cu terasă panoramică, la etajul 9 din 10 într-un ansamblu "
        "livrat în 2022 de un dezvoltator cu bonitate A+. Starea tehnică este foarte bună — trei "
        "defecte minore, toate estetice, cu un buget total de remediere de 300 €. Prețul cerut "
        "depășește valoarea de piață estimată cu 4,9%, ceea ce lasă o marjă de negociere "
        "argumentabilă de circa 17.000 €. Riscul principal nu este tehnic, ci de lichiditate la "
        "revânzare: segmentul de peste 300.000 € din nordul Bucureștiului are un timp mediu de "
        "expunere de 5-7 luni."
    ),
    "puncte_forte": [
        "Dezvoltator cu cifră de afaceri de 145,8 mil. RON și grad de îndatorare de 0,29 — "
        "fără profil de SPV.",
        "Structură din beton armat C30/37 și certificare BREEAM Excellent, clasa "
        "energetică A (nZEB ready).",
        "Terasă circulabilă cu hidroizolație dublă termosudată și termoizolație PIR de 20 cm.",
        "Pachet de electrocasnice premium în valoare actuală de 6.310 €, inclus în preț.",
        "Intabulat individual, liber de sarcini, cu carte tehnică completă la asociație.",
    ],
    "puncte_slabe": [
        "Preț cerut cu 4,9% peste valoarea de piață estimată prin comparație.",
        "Cost lunar de administrare peste media zonei, din cauza întreținerii parcului privat.",
        "Trafic intens pe Șoseaua Pipera la orele de vârf, semnalat constant în recenzii.",
        "Lichiditate redusă la revânzare pe segmentul de preț peste 300.000 €.",
    ],
    "metodologie": {
        "standard": (
            "SEV 2025 (ediția în vigoare) · GEV 630 · structura raportului conform SEV 106 §30.6"
        ),
        "tip_valoare": "Valoare de piață, conform SEV 102 — Tipuri ale valorii",
        "data_evaluarii": "10.09.2026",
        "moneda": "EUR",
        "client": "Beneficiarul analizei (cumpărător potențial)",
        "utilizare_desemnata": "Fundamentarea deciziei de achiziție și a nivelului de ofertare",
        "utilizator_desemnat": "Exclusiv clientul; nu se autorizează difuzarea către terți",
        "evaluator": (
            "NEÎNDEPLINIT — analiză automată, fără evaluator autorizat ANEVAR. Documentul nu "
            "este și nu înlocuiește un raport de evaluare autorizat."
        ),
        "amploare": (
            "FĂRĂ inspecție fizică a proprietății și fără verificarea actelor de proprietate. "
            "Analiza se bazează exclusiv pe datele publice ale anunțului, pe fotografiile "
            "publicate, pe imagini Google Street View și pe surse deschise."
        ),
        "surse_date": [
            "Anunțul imobiliare.ro și galeria foto publicată de vânzător",
            "Comparabile din oferte active și tranzacții raportate în aceeași arie",
            "Google Maps Platform — geocodare, Places, Routes, Street View Static",
            "Ortofotoplan Esri World Imagery pentru imaginea aeriană",
            "Targetare.ro / date financiare publice ANAF pentru bonitatea dezvoltatorului",
            "Recenzii publice Google Maps ale ansamblului rezidențial",
        ],
    },
    "ipoteze_limitative": [
        "Se presupune un titlu de proprietate valabil, liber de sarcini neînregistrate.",
        "Suprafețele sunt cele declarate în anunț; nu au fost măsurate independent.",
        "Nu s-au efectuat teste asupra structurii, instalațiilor sau prezenței substanțelor "
        "periculoase.",
        "Defectele identificate provin exclusiv din analiza fotografiilor publicate — un viciu "
        "ascuns nefotografiat nu poate fi detectat.",
        "Valorile electrocasnicelor sunt estimări de piață secundară, nu evaluări individuale "
        "de bunuri mobile.",
        "Evaluarea presupune vânzare în condiții normale, cu expunere adecvată pe piață.",
    ],
    "analiza_piata": {
        "zona": "București Nord — Aviației / Pipera, Sector 1",
        "pret_mediu_zona_eur_mp": 2790,
        "variatie_anuala_procent": 4.2,
        "timp_mediu_expunere_luni": 5.5,
        "oferta_activa_similara": 34,
        "tendinta": "Creștere moderată, cu cerere concentrată pe ansambluri finalizate după 2020",
        "comentariu": (
            "Cererea în Aviației rămâne susținută de proximitatea față de zona de birouri "
            "Băneasa–Pipera și de metroul Aurel Vlaicu. Segmentul de 2-3 camere sub 250.000 € se "
            "tranzacționează în 2-3 luni; penthouse-urile de peste 300.000 € au o expunere "
            "sensibil mai lungă, ceea ce sprijină o poziție de negociere fermă a cumpărătorului."
        ),
    },
    "cea_mai_buna_utilizare": (
        "Utilizarea actuală — locuință rezidențială premium ocupată de proprietar — este și cea "
        "mai bună utilizare: este permisă legal (PUZ rezidențial), posibilă fizic, fezabilă "
        "financiar și produce valoarea maximă. Conversia în regim de închiriere pe termen scurt "
        "este restricționată prin regulamentul asociației de proprietari."
    ),
    "esg": {
        "certificare": "BREEAM Excellent",
        "clasa_energetica": "A (nZEB ready)",
        "consum_specific_kwh_mp_an": 78,
        "riscuri_climatice": (
            "Zonă seismică ag = 0,30 g, Tc = 1,6 s (P100-1/2013); structura este proiectată "
            "post-2012, la cerințele actuale de rezistență seismică. Fără risc de inundabilitate "
            "conform hărților ANAR."
        ),
        "social": "Parc privat de 11.000 mp, pază 24/7, acces controlat la parcarea subterană.",
        "guvernanta": "Asociație de proprietari constituită, carte tehnică arhivată și accesibilă.",
    },
    "riscuri": [
        {
            "risc": "Preț cerut peste valoarea de piață estimată",
            "probabilitate": "Certă",
            "impact": "Ridicat",
            "mitigare": (
                "Negociere ancorată pe cele trei comparabile din ansamblu; țintă 328.000 €."
            ),
        },
        {
            "risc": "Lichiditate redusă la revânzare (segment peste 300.000 €)",
            "probabilitate": "Medie",
            "impact": "Mediu",
            "mitigare": (
                "Orizont de deținere de minimum 5 ani pentru amortizarea costurilor de "
                "tranzacționare."
            ),
        },
        {
            "risc": "Costuri de administrare peste media zonei",
            "probabilitate": "Certă",
            "impact": "Scăzut",
            "mitigare": (
                "Solicitarea bugetului asociației pe ultimele 12 luni înainte de antecontract."
            ),
        },
        {
            "risc": "Micro-fisuri de contracție în gips-carton",
            "probabilitate": "Certă",
            "impact": "Scăzut",
            "mitigare": "Remediere 150 €; se verifică la vizionare dacă fisura este stabilizată.",
        },
        {
            "risc": "Expunere la zgomot dinspre Șoseaua Pipera",
            "probabilitate": "Medie",
            "impact": "Mediu",
            "mitigare": (
                "Vizionare la ora de vârf, cu ferestrele deschise, pentru verificarea izolării "
                "fonice."
            ),
        },
    ],
    "costuri_detinere": {
        "intretinere_lunara_eur": 185,
        "impozit_anual_eur": 210,
        "asigurare_anuala_eur": 145,
        "fond_reparatii_lunar_eur": 45,
        "total_anual_eur": 3115,
        "comentariu": (
            "Costurile de administrare includ întreținerea parcului privat de 11.000 mp și paza "
            "permanentă — sunt peste media zonei, dar corespund serviciilor efectiv prestate."
        ),
    },
    "costuri_tranzactionare": {
        "onorariu_notarial_procent": 1.1,
        "taxa_intabulare_procent": 0.15,
        "comision_agentie_procent": 2.0,
        "total_estimat_eur": 11200,
    },
    "receptie_checklist": {
        "conformitate_carte_tehnica": "Completă și arhivată la asociația de proprietari.",
        "garantie_legala_structura": ("50 ani (garanție pe durata de viață conf. Legii 10/1995)."),
        "garantie_finisaje_echipamente": "2 ani pentru finisaje și vicii aparente.",
        "cadastru_si_intabulare": "Intabulat individual, liber de sarcini și ipoteci bancare.",
        "certificat_energetic": "Clasa A, consum specific redus de energie.",
    },
    "lat": 44.4795,
    "lon": 26.0988,
    "locatie": {
        "status": "success",
        "lat": 44.4795,
        "lon": 26.0988,
        "adresa_formatata": "Șoseaua Pipera 4B, Sector 1, București",
        "precizie": "adresa",
        "google_maps_url": "https://www.google.com/maps/search/?api=1&query=44.4795,26.0988",
        "scor_accesibilitate": 9.4,
        "total_facilitati": 18,
        "harta": {
            "url": "/api/audit/imagery/roadmap?lat=44.4795&lon=26.0988&zoom=16&w=640&h=640",
            "zoom": 16,
            "latime": 640,
            "inaltime": 640,
            "raza_m": 500,
            "metri_pe_pixel": 1.25,
            "atribuire": "Hartă © Google",
        },
        "satelit": {
            "url": "/api/audit/imagery/aerial?lat=44.4795&lon=26.0988&zoom=18&w=640&h=480",
            "zoom": 18,
            "atribuire": "Esri, Maxar, Earthstar Geographics",
        },
        "street_view": {
            "disponibil": True,
            "data_captura": "2023-08",
            "copyright": "© Google",
            "unghiuri": [
                {"heading": 0, "eticheta": "Fațada clădirii", "url": "/api/audit/imagery/streetview?lat=44.4795&lon=26.0988&heading=0&w=480&h=320"},
                {"heading": 90, "eticheta": "Acces stradal est", "url": "/api/audit/imagery/streetview?lat=44.4795&lon=26.0988&heading=90&w=480&h=320"},
                {"heading": 180, "eticheta": "Perspectivă sud", "url": "/api/audit/imagery/streetview?lat=44.4795&lon=26.0988&heading=180&w=480&h=320"},
                {"heading": 270, "eticheta": "Perspectivă vest", "url": "/api/audit/imagery/streetview?lat=44.4795&lon=26.0988&heading=270&w=480&h=320"},
            ],
        },
        "facilitati": {
            "metrou": [
                {"nume": "Stația de Metrou Aurel Vlaicu (M2)", "categorie": "metrou", "distanta_m": 420, "minute_mers": 5, "rating": 4.6, "lat": 44.4781, "lon": 26.1012},
            ],
            "transport": [
                {"nume": "Stația STB Calea Floreasca (Linii 135, 112)", "categorie": "transport", "distanta_m": 160, "minute_mers": 2, "rating": 4.2, "lat": 44.4790, "lon": 26.0975},
                {"nume": "Stația Tramvai Barbu Văcărescu (Linia 5)", "categorie": "transport", "distanta_m": 380, "minute_mers": 5, "rating": 4.0, "lat": 44.4775, "lon": 26.1020},
            ],
            "parcuri": [
                {"nume": "Parcul Herăstrău (Regele Mihai I)", "categorie": "parcuri", "distanta_m": 650, "minute_mers": 8, "rating": 4.8, "lat": 44.4820, "lon": 26.0910},
                {"nume": "Parcul Bordei", "categorie": "parcuri", "distanta_m": 480, "minute_mers": 6, "rating": 4.6, "lat": 44.4760, "lon": 26.0935},
            ],
            "supermarket": [
                {"nume": "Mega Image Concept Store Barbu Văcărescu", "categorie": "supermarket", "distanta_m": 280, "minute_mers": 3, "rating": 4.4, "lat": 44.4780, "lon": 26.0960},
                {"nume": "Carrefour Express Pipera", "categorie": "supermarket", "distanta_m": 350, "minute_mers": 4, "rating": 4.2, "lat": 44.4810, "lon": 26.1025},
                {"nume": "Lidl Pipera", "categorie": "supermarket", "distanta_m": 490, "minute_mers": 6, "rating": 4.3, "lat": 44.4825, "lon": 26.1040},
            ],
            "mall": [
                {"nume": "Promenada Mall București", "categorie": "mall", "distanta_m": 490, "minute_mers": 6, "rating": 4.6, "lat": 44.4770, "lon": 26.1045},
            ],
            "medical": [
                {"nume": "Clinica Regina Maria Pipera", "categorie": "medical", "distanta_m": 390, "minute_mers": 5, "rating": 4.5, "lat": 44.4805, "lon": 26.1030},
                {"nume": "Centrul Medical Medicover Floreasca", "categorie": "medical", "distanta_m": 520, "minute_mers": 7, "rating": 4.3, "lat": 44.4755, "lon": 26.0980},
            ],
            "scoli": [
                {"nume": "Școala Gimnazială Herăstrău", "categorie": "scoli", "distanta_m": 450, "minute_mers": 6, "rating": 4.3, "lat": 44.4815, "lon": 26.0940},
            ],
            "gradinite": [
                {"nume": "Grădinița Little Learners Aviației", "categorie": "gradinite", "distanta_m": 310, "minute_mers": 4, "rating": 4.7, "lat": 44.4785, "lon": 26.0950},
            ],
            "sport": [
                {"nume": "World Class Upground & Piscină", "categorie": "sport", "distanta_m": 430, "minute_mers": 5, "rating": 4.5, "lat": 44.4765, "lon": 26.1035},
            ],
            "farmacii": [
                {"nume": "Farmacia Catena Promenada", "categorie": "farmacii", "distanta_m": 490, "minute_mers": 6, "rating": 4.3, "lat": 44.4771, "lon": 26.1044},
                {"nume": "Farmacia Dr. Max Pipera", "categorie": "farmacii", "distanta_m": 320, "minute_mers": 4, "rating": 4.2, "lat": 44.4800, "lon": 26.1010},
            ],
        },
        "meta_categorii": {
            "metrou": {"eticheta": "Metrou", "icon": "train-front", "culoare": "#4338ca"},
            "transport": {"eticheta": "Transport public", "icon": "bus", "culoare": "#0891b2"},
            "parcuri": {"eticheta": "Parcuri", "icon": "trees", "culoare": "#15803d"},
            "supermarket": {"eticheta": "Supermarketuri", "icon": "shopping-cart", "culoare": "#0284c7"},
            "mall": {"eticheta": "Centre comerciale", "icon": "shopping-bag", "culoare": "#7c3aed"},
            "medical": {"eticheta": "Medical", "icon": "stethoscope", "culoare": "#e11d48"},
            "scoli": {"eticheta": "Școli", "icon": "school", "culoare": "#c2410c"},
            "gradinite": {"eticheta": "Grădinițe & creșe", "icon": "baby", "culoare": "#db2777"},
            "sport": {"eticheta": "Sport & fitness", "icon": "dumbbell", "culoare": "#ea580c"},
            "farmacii": {"eticheta": "Farmacii", "icon": "pill", "culoare": "#dc2626"},
        },
    },
}
