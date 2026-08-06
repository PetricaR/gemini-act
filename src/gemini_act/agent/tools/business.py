"""Custom business tools.

This is where domain actions go. ADK builds each tool's schema from the
signature, type hints and docstring, so all three are load-bearing: describe
arguments precisely and always return a dict carrying a "status" key so the
model can tell success from failure without guessing.

The three below are worked examples — replace them with real integrations.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# Where a "risky" action would consult an allowlist. Shell and filesystem tools,
# if ever added, belong behind a gate like this one and never open to a space.
APPROVED_ACTION_USERS: set[str] = set()


def current_time(timezone: str = "UTC") -> dict[str, Any]:
    """Get the current date and time in a given IANA timezone.

    Args:
        timezone: IANA timezone name, e.g. "Europe/Bucharest" or "UTC".

    Returns:
        A dict with "status", and on success "timezone", "iso" (ISO-8601
        timestamp) and "human" (a readable rendering); on error an
        "error_message".
    """
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return {
            "status": "error",
            "error_message": (
                f"Unknown timezone {timezone!r}. Use an IANA name like 'Europe/Paris'."
            ),
        }
    now = datetime.now(UTC).astimezone(zone)
    return {
        "status": "success",
        "timezone": timezone,
        "iso": now.isoformat(),
        "human": now.strftime("%A %d %B %Y, %H:%M"),
    }


async def lookup_reference_data(entity: str, identifier: str) -> dict[str, Any]:
    """Look up a record in an internal reference system.

    Replace the stub body with a real HTTP call to your service.

    Args:
        entity: The kind of record, e.g. "store", "product" or "supplier".
        identifier: The record's identifier, e.g. a store code or SKU.

    Returns:
        A dict with "status", and on success "entity", "identifier" and
        "record"; on error an "error_message".
    """
    known = {
        ("store", "1234"): {"name": "Example Store", "city": "Bucharest", "format": "Hyper"},
        ("product", "SKU-001"): {"name": "Example Product", "unit": "each", "active": True},
    }
    record = known.get((entity.lower(), identifier))
    if record is None:
        return {
            "status": "error",
            "error_message": f"No {entity} found with identifier {identifier!r}.",
        }
    return {"status": "success", "entity": entity, "identifier": identifier, "record": record}


def summarize_numbers(values: list[float], label: str = "values") -> dict[str, Any]:
    """Compute basic statistics over a list of numbers.

    Args:
        values: The numbers to summarize. Must not be empty.
        label: A short name for what the numbers represent, echoed back.

    Returns:
        A dict with "status", and on success "label", "count", "total", "mean",
        "minimum" and "maximum"; on error an "error_message".
    """
    if not values:
        return {"status": "error", "error_message": "No values supplied."}
    total = float(sum(values))
    return {
        "status": "success",
        "label": label,
        "count": len(values),
        "total": total,
        "mean": total / len(values),
        "minimum": min(values),
        "maximum": max(values),
    }


BUSINESS_TOOLS = [current_time, lookup_reference_data, summarize_numbers]
