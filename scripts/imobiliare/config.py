"""Setările de care are nevoie evaluarea imobiliară.

Deliberat separate de `gemini_act.config`: pachetul acesta rulează și singur, ca
server MCP (`imobiliare-mcp`), fără agentul de Chat în proces. Citește însă
*aceleași* variabile de mediu ca înainte — același prefix `GEMINI_ACT_`, aceleași
nume de câmpuri — ca să nu fie nevoie de schimbări în `.env`, în `deploy/` sau în
Cloud Run.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GEMINI_ACT_",
        env_file=".env",
        extra="ignore",
        # Câmpurile cu alias sunt altfel setabile *doar* prin alias: numele
        # câmpului e ignorat în tăcere, lăsând valoarea implicită. Vezi nota
        # identică din `gemini_act.config`.
        populate_by_name=True,
    )

    # Proiectul și regiunea GCP, pentru apelurile Gemini Vision din `mcp/viziune.py`.
    project: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")
    location: str = Field(default="global", alias="GOOGLE_CLOUD_LOCATION")

    # Comutatorul principal al tool-urilor de proprietăți. Căutarea are nevoie de
    # o sesiune capturată din browser și e deci nesigură; calea de evaluare nu —
    # își ia comparabilele din sitemap-urile publice și le hidratează neautentificat.
    imobiliare_enabled: bool = True

    # API-ul explorer imo360 (`mcp/imo360.py`): a doua sursă, geografică în loc de
    # textuală, neautentificată, și singura de aici care are chirii — deci ea face
    # randamentul calculabil. Comutator propriu pentru că e alt upstream și poate
    # fi închisă independent.
    imo360_enabled: bool = True

    # imoradar24.ro (`mcp/imoradar.py`): a treia sursă și singurul agregator — indexează
    # imobiliare.ro, storia.ro, olx.ro, publi24.ro și altele deodată, ceea ce atinge
    # segmentul *proprietar* (OLX și Publi24 îl au; nimic altceva de aici nu-l are).
    imoradar_enabled: bool = True

    # Comparabile duse în grila GEV 630 §54-58. Mai multe nu înseamnă mai bine:
    # grila oricum ponderează după similaritate, iar fiecare e un rând de hidratat.
    imobiliare_comparables: int = 12

    # Capturat din browser (DevTools > Network > /api/search > request body).
    # Expiră în câteva minute, deci `cauta` e best-effort, iar tot ce contează
    # (`detalii`, `evaluare`) e construit să meargă fără el.
    imobiliare_session_id: str = ""

    # Câte fotografii ale anunțului ajung la modelul de vision. Galeria întreagă
    # ar fi 30-40 de imagini pe o ofertă bine fotografiată; primele două duzini
    # acoperă deja fiecare cameră, iar fiecare în plus înseamnă tokeni și latență.
    imobiliare_max_photos: int = 24

    # Lasă modelul să se uite efectiv la fotografii, în loc să primească o cale
    # de fișier pe care n-o poate deschide — vezi `mcp/viziune.py`.
    imobiliare_vision_enabled: bool = True

    # Modelul folosit pentru acea trecere. Separat de `model` intenționat: apelul
    # de vision e o singură cerere fără stare și fără tool-uri, deci poate fi fixat
    # sau coborât independent de ce servește conversația.
    imobiliare_vision_model: str = "gemini-3.8-flash"

    # Cheia Google Maps Platform, folosită server-side de pipeline-ul de evaluare
    # pentru geocodare, facilități, timpi de mers și harta locației.
    #
    # Gol este o configurație suportată, nu una stricată: totul degradează către
    # calea OpenStreetMap (Nominatim + Overpass) pe care `mcp/locatie.py` o
    # implementează deja — gratuită, dar mai grosieră și mult mai lentă.
    maps_api_key: str = ""

    # Raza căutării de facilități în jurul proprietății, în metri.
    maps_amenity_radius_m: int = 1200


def get_settings() -> Settings:
    # Necachat, exact ca `gemini_act.config.get_settings`: testele setează
    # variabile de mediu și se așteaptă ca apelul următor să le vadă.
    return Settings()
