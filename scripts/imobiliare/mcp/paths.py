"""Where this package is allowed to write.

Cloud Run's filesystem is read-only apart from ``/tmp``, and ``Path.home()``
there is not writable either -- so every disk write in this package has to go
through one of the helpers below rather than assuming a home directory or the
process working directory exists and is writable.

An explicit override always wins, then the home directory when it is genuinely
writable (a developer's machine), then a temp directory.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _writable_base(env_var: str, home_relative: str, temp_name: str) -> Path:
    if override := os.environ.get(env_var):
        return Path(override)
    home = Path.home()
    if os.access(home, os.W_OK):
        return home / home_relative
    return Path(tempfile.gettempdir()) / temp_name


def cache_dir(*parts: str) -> Path:
    """A cache directory that is safe to write to on Cloud Run."""
    base = _writable_base(
        "IMOBILIARE_CACHE_DIR", ".cache/imobiliare-mcp", "imobiliare-mcp-cache"
    )
    return base.joinpath(*parts) if parts else base


def reports_dir() -> Path:
    """Where reports and their side files are staged.

    The report is delivered to the user as a Chat attachment either way; this
    path is where it is staged, not where it is kept.
    """
    return _writable_base(
        "IMOBILIARE_REPORTS_DIR", "imobiliare-rapoarte", "imobiliare-rapoarte"
    )


def ensure_dir(path: Path) -> Path | None:
    """``mkdir -p`` that degrades instead of raising on a read-only filesystem.

    Returns the path when it is usable, ``None`` when the filesystem refused --
    callers treat that as "caching/staging unavailable", not as a failure of
    whatever they were actually doing.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return path
