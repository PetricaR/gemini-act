"""Fold a listing's gallery into one contact sheet.

A valuation done at a distance has no inspection; the photographs are the
only evidence about condition, layout and light. One sheet is far easier to
read -- for a person or a vision model -- than a dozen separate files.
"""

from __future__ import annotations

import io
from pathlib import Path

import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.imobiliare.ro/",
}


def contact_sheet(urls: list[str], destination: Path, columns: int = 3,
                  cell: tuple[int, int] = (420, 315)) -> Path | None:
    """Download a gallery and tile it. Returns None if Pillow is absent."""
    try:
        from PIL import Image
    except ImportError:
        return None
    if not urls:
        return None

    tiles = []
    with httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True) as http:
        for url in urls:
            try:
                r = http.get(url)
                if r.status_code == 200:
                    im = Image.open(io.BytesIO(r.content)).convert("RGB")
                    im.thumbnail(cell)
                    tiles.append(im)
            except Exception:      # one unreachable photo must not lose the sheet
                continue
    if not tiles:
        return None

    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell[0], rows * cell[1]), "white")
    for i, im in enumerate(tiles):
        x = (i % columns) * cell[0] + (cell[0] - im.width) // 2
        y = (i // columns) * cell[1] + (cell[1] - im.height) // 2
        sheet.paste(im, (x, y))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, quality=82)
    return destination
