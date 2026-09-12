"""Obscura headless browser integration for imobiliare.ro search and automation.

Provides:
- Binary resolution & auto-installation for Obscura
- Headless browser client wrapping Obscura CLI (fetch, eval, scrape, cookies)
- Autonomous imobiliare search engine that requires NO temporary browser session
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .server import Filters, SortBy

logger = logging.getLogger(__name__)

# Common Bucharest neighbourhoods for query area extraction
BUCHAREST_AREAS = [
    "titan",
    "dristor",
    "floreasca",
    "aviatiei",
    "pipera",
    "militari",
    "drumul taberei",
    "pantelimon",
    "colentina",
    "berceni",
    "tineretului",
    "unirii",
    "universitate",
    "romana",
    "victoriei",
    "dorobanti",
    "primaverii",
    "baneasa",
    "crangasi",
    "giulesti",
    "rahova",
    "ferentari",
    "vitan",
    "tecolentina",
    "bucurestii noi",
    "damaroaia",
    "grozavesti",
    "cotroceni",
    "mosilor",
    "obor",
    "iancului",
    "muncii",
    "decebal",
    "timpuri noi",
    "sector 1",
    "sector 2",
    "sector 3",
    "sector 4",
    "sector 5",
    "sector 6",
]

# Major Romanian cities mapping to county scope
CITY_TO_SCOPE: dict[str, str] = {
    "bucuresti": "bucuresti",
    "bucharest": "bucuresti",
    "cluj": "judetul-cluj",
    "cluj-napoca": "judetul-cluj",
    "timisoara": "judetul-timis",
    "timis": "judetul-timis",
    "iasi": "judetul-iasi",
    "brasov": "judetul-brasov",
    "constanta": "judetul-constanta",
    "sibiu": "judetul-sibiu",
    "oradea": "judetul-bihor",
    "bihor": "judetul-bihor",
    "craiova": "judetul-dolj",
    "dolj": "judetul-dolj",
    "arad": "judetul-arad",
    "ploiesti": "judetul-prahova",
    "prahova": "judetul-prahova",
    "ilfov": "judetul-ilfov",
}


@dataclass(frozen=True)
class ObscuraResult:
    """Result of an Obscura CLI invocation."""

    success: bool
    output: str
    title: str | None = None
    page_url: str | None = None
    error: str | None = None
    data: Any = None


def _slugify(text: str) -> str:
    """Normalize text into ASCII slug."""
    stripped = unicodedata.normalize("NFKD", text or "")
    ascii_only = "".join(c for c in stripped if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")


def find_obscura_bin() -> str | None:
    """Locate the obscura executable binary."""
    # 1. Explicit env var
    if env_bin := os.environ.get("OBSCURA_BIN"):
        if Path(env_bin).is_file() and os.access(env_bin, os.X_OK):
            return str(Path(env_bin).resolve())

    # 2. Check system PATH
    if path_bin := shutil.which("obscura"):
        return path_bin

    # 3. Standard user / system locations
    candidates = [
        Path("/usr/local/bin/obscura"),
        Path("/usr/bin/obscura"),
        Path.home() / ".local/bin/obscura",
        Path.cwd() / "obscura",
        Path(__file__).resolve().parents[4] / "obscura",
        Path(__file__).resolve().parents[3] / "obscura",
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c.resolve())

    return None


def ensure_obscura_bin() -> str:
    """Return obscura path, or run install script if missing."""
    found = find_obscura_bin()
    if found:
        return found

    # Run the installation script if present
    script = Path(__file__).resolve().parents[3] / "scripts/install_obscura.sh"
    if script.is_file():
        logger.info("Obscura binary not found. Running installer %s...", script)
        try:
            res = subprocess.run(
                ["bash", str(script)],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if res.returncode == 0:
                found = find_obscura_bin()
                if found:
                    return found
        except Exception as exc:
            logger.warning("Failed to auto-install Obscura via script: %s", exc)

    raise FileNotFoundError(
        "Obscura binary not found. Please run scripts/install_obscura.sh or set OBSCURA_BIN."
    )


class ObscuraBrowser:
    """Wrapper around the Obscura stealth headless browser."""

    def __init__(self, binary_path: str | None = None) -> None:
        self.binary_path = binary_path or find_obscura_bin()

    def is_available(self) -> bool:
        return self.binary_path is not None and Path(self.binary_path).is_file()

    def fetch(
        self,
        url: str,
        eval_js: str | None = None,
        stealth: bool = True,
        timeout: int = 45,
        wait: int = 3,
        wait_until: str = "domcontentloaded",
        dump: str | None = None,
    ) -> ObscuraResult:
        """Fetch a page, optionally evaluating JS or dumping cookies/content."""
        bin_path = self.binary_path or ensure_obscura_bin()
        cmd = [bin_path, "fetch", url]

        if stealth:
            cmd.append("--stealth")
        cmd.extend(["--timeout", str(timeout)])
        cmd.extend(["--wait", str(wait)])
        cmd.extend(["--wait-until", wait_until])

        if eval_js:
            cmd.extend(["--eval", eval_js])
        if dump:
            cmd.extend(["--dump", dump])

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 20,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ObscuraResult(
                success=False,
                output="",
                error=f"Obscura fetch timed out after {timeout}s: {exc}",
            )
        except Exception as exc:
            return ObscuraResult(
                success=False,
                output="",
                error=f"Failed to execute Obscura: {exc}",
            )

        output = res.stdout.strip()
        err = res.stderr.strip()

        # Parse page title and url if present in stdout
        title: str | None = None
        page_url: str | None = None
        for line in output.splitlines():
            if line.startswith("Page loaded: "):
                # e.g. Page loaded: https://... - "Title"
                m = re.match(r'Page loaded:\s+(\S+)\s+-\s+"([^"]*)"', line)
                if m:
                    page_url = m.group(1)
                    title = m.group(2)

        data = None
        try:
            # If the evaluated JS returned JSON or dump is JSON
            if output.startswith(("{", "[")) and output.endswith(("}", "]")):
                data = json.loads(output)
        except Exception:
            pass

        return ObscuraResult(
            success=(res.returncode == 0),
            output=output,
            title=title,
            page_url=page_url,
            error=err if res.returncode != 0 else None,
            data=data,
        )

    def scrape(self, urls: list[str]) -> ObscuraResult:
        """Run obscura scrape across given URLs."""
        bin_path = self.binary_path or ensure_obscura_bin()
        cmd = [bin_path, "scrape", *urls]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            return ObscuraResult(
                success=(res.returncode == 0),
                output=res.stdout.strip(),
                error=res.stderr.strip() if res.returncode != 0 else None,
            )
        except Exception as exc:
            return ObscuraResult(
                success=False,
                output="",
                error=f"Obscura scrape failed: {exc}",
            )

    def get_cookies(self, url: str) -> list[dict[str, Any]]:
        """Fetch cookies for a given URL using Obscura."""
        res = self.fetch(url, dump="cookies", wait=3)
        if res.success and isinstance(res.data, list):
            return res.data
        return []


def parse_query_intent(query: str) -> dict[str, Any]:
    """Extract real estate search parameters from a natural-language query."""
    q = query.lower()

    # Deal type
    deal = "rent" if any(w in q for w in ["inchiriat", "chirie", "rent", "inchiriere"]) else "sale"

    # Rooms
    rooms: int | None = None
    if "garsonier" in q or "1 camer" in q or "o camer" in q or "studio" in q:
        rooms = 1
    elif "2 camer" in q or "doua camer" in q:
        rooms = 2
    elif "3 camer" in q or "trei camer" in q:
        rooms = 3
    elif "4 camer" in q or "patru camer" in q:
        rooms = 4
    elif m := re.search(r"(\d+)\s*camer", q):
        rooms = int(m.group(1))

    # City / Scope
    scope = "bucuresti"
    for city, mapped_scope in CITY_TO_SCOPE.items():
        if city in q:
            scope = mapped_scope
            break

    # Area / Zone
    area: str | None = None
    for a in sorted(BUCHAREST_AREAS, key=len, reverse=True):
        if a in q:
            area = _slugify(a)
            break

    # Price max extraction
    price_max: int | None = None
    if m := re.search(
        r"(?:sub|pana in|maxim|max|buget(?: de)?)\s*(\d+)(?:\s*(?:k|000|mii))?\s*(?:eur|euro|€)?", q
    ):
        val = int(m.group(1))
        if val < 1000:
            val *= 1000
        price_max = val

    # Price min extraction
    price_min: int | None = None
    if m := re.search(
        r"(?:peste|minim|min|de la)\s*(\d+)(?:\s*(?:k|000|mii))?\s*(?:eur|euro|€)?", q
    ):
        val = int(m.group(1))
        if val < 1000:
            val *= 1000
        price_min = val

    return {
        "deal": deal,
        "rooms": rooms,
        "scope": scope,
        "area": area,
        "price_max": price_max,
        "price_min": price_min,
    }


def search_imobiliare_obscura(
    query: str,
    filters: Filters | None = None,
    sort: SortBy = "metro",
    limit: int = 20,
    pool_size: int = 60,
) -> dict[str, Any]:
    """Search imobiliare.ro without requiring a temporary browser session.

    Combines:
    1. Query intent extraction (area, rooms, price, deal type)
    2. Sitemaps candidate sourcing via comps.offers()
    3. Unauthenticated fast listing hydration via ImobiliareClient.hydrate()
    4. Normalization, filtering, and sorting matching the standard tool output
    """
    from . import comps
    from .client import ImobiliareClient
    from .parse import normalise
    from .server import _apply

    intent = parse_query_intent(query)
    target_scope = intent["scope"]
    target_deal = intent["deal"]
    target_rooms = (filters.camere if filters and filters.camere else None) or intent["rooms"]
    target_area = (filters.zona if filters and filters.zona else None) or intent["area"]

    # Gather candidate offers from the published sitemap
    try:
        all_offers = comps.offers(scope=target_scope, deal=target_deal)
    except Exception as exc:
        logger.warning("Failed to fetch sitemap for %s: %s", target_scope, exc)
        all_offers = []

    matched_offers = all_offers

    # Filter candidates by room count
    if target_rooms is not None:
        matched_offers = [o for o in matched_offers if o.rooms == target_rooms]

    # Filter candidates by area if detected
    if target_area:
        slug_area = _slugify(target_area)
        area_matched = [o for o in matched_offers if slug_area in o.area or slug_area in o.slug]
        if area_matched:
            matched_offers = area_matched

    # Slice top pool candidates
    candidate_ids = [o.id for o in matched_offers[:pool_size]]

    # Hydrate listings without requiring any session token
    client = ImobiliareClient()
    raw_listings = client.hydrate(candidate_ids) if candidate_ids else []

    # Normalise listings into standard format
    records = [normalise(item) for item in raw_listings]

    # Apply filters and sorting
    effective_filters = filters
    if effective_filters is None:
        from .server import Filters

        effective_filters = Filters(
            pret_max=intent["price_max"],
            pret_min=intent["price_min"],
            camere=target_rooms,
        )

    matches, page = _apply(records, effective_filters, sort, limit)

    return {
        "title": f"Căutare Obscura: {query}",
        "assistant_reply": (
            f"Am căutat '{query}' folosind motorul autonom Obscura "
            f"(sursa: {len(all_offers)} oferte din sitemap, {len(raw_listings)} verificate)."
        ),
        "engine": "obscura",
        "total_hits_before_filters": len(all_offers),
        "retrieved": len(records),
        "matched": len(matches),
        "returned": len(page),
        "resume_token": None,
        "listings": page,
    }
