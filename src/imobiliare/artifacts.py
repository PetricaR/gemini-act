"""Files a tool produced, held for the reply that sends them.

`chat/reply_attachment.py` lets the model attach a file it composed itself, by
base64-ing the bytes into its own answer. That works because the files it has in
mind are small — a few-line CSV, a short note.

It does not work for a file a *tool* produced. A valuation report is 20-40 KB of
markdown; asking the model to reproduce it as base64 would put ~50 KB of
generated tokens on the critical path, cost real money per report, and fail
often — long base64 is exactly the kind of output a model truncates or corrupts,
and a corrupted attachment is indistinguishable from a working one until the
user opens it.

So the bytes never enter the conversation. The tool stores them here and gets a
short token back; the model only ever handles that token; `events.py` swaps it
for the bytes on the way out. The model stays in charge of *whether* to send the
file — it just no longer has to carry it.

Process-local, and that is sufficient: the agent turn and the reply that follows
it run in the same background task in the same process (see `chat/events.py`).
A token that outlives its process resolves to nothing, and the caller reports a
missing attachment rather than sending the wrong one.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

# Long enough that a token from an earlier turn in a long conversation still
# resolves, short enough that a forgotten report is not held for the life of the
# instance. Reports are staged on disk as well, so this expiring is recoverable.
TTL_SECONDS = 30 * 60

# A ceiling on what one process will hold at once. Reports are tens of KB, so
# this is generous; it exists so a runaway loop cannot exhaust the instance.
MAX_ENTRIES = 32


@dataclass(frozen=True)
class Artifact:
    filename: str
    mime_type: str
    data: bytes
    created_at: float


_store: dict[str, Artifact] = {}
_lock = threading.Lock()


def _evict(now: float) -> None:
    """Drop what has expired, then the oldest if still over the cap.

    Called under `_lock` by both entry points.
    """
    for token in [t for t, a in _store.items() if now - a.created_at > TTL_SECONDS]:
        del _store[token]
    while len(_store) > MAX_ENTRIES:
        oldest = min(_store, key=lambda t: _store[t].created_at)
        del _store[oldest]


def put(filename: str, mime_type: str, data: bytes) -> str:
    """Hold a file and return the token that stands for it."""
    token = f"art_{secrets.token_urlsafe(9)}"
    now = time.time()
    with _lock:
        _store[token] = Artifact(filename, mime_type, data, now)
        _evict(now)
    return token


def take(token: str) -> Artifact | None:
    """Resolve a token, consuming it.

    Consuming rather than peeking: an artifact is sent once. A model that
    repeats the same token in a later turn gets a miss, which surfaces as "that
    file is no longer available" instead of silently re-sending a stale report
    the user has already been given.
    """
    with _lock:
        return _store.pop(token, None)


def peek(token: str) -> Artifact | None:
    """Resolve without consuming. For checks that must not spend the artifact."""
    with _lock:
        return _store.get(token)
