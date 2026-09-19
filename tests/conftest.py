from __future__ import annotations

import os

import pytest

# Set before any gemini_act import so Settings never reaches for Firestore or ADC.
os.environ.setdefault("GEMINI_ACT_TOKEN_STORE", "memory")
os.environ.setdefault("GEMINI_ACT_VERIFY_CHAT_REQUESTS", "FALSE")
os.environ.setdefault("GEMINI_ACT_PUBLIC_BASE_URL", "https://test.example.com")
os.environ.setdefault("GEMINI_ACT_CHAT_AUDIENCE", "https://test.example.com")
os.environ.setdefault("GEMINI_ACT_STATE_SECRET", "test-secret")
os.environ.setdefault("GEMINI_ACT_OAUTH_CLIENT_ID", "test-client-id")
os.environ.setdefault("GEMINI_ACT_OAUTH_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")

# `imobiliare_mcp.throttle` reads its pacing from the environment at import
# time. Left at its defaults the suite would sleep over a second before every
# stubbed image fetch, so the pace is flattened here — what the tests care
# about is the de-duplication and the block detection, not the sleeping.
os.environ.setdefault("IMOBILIARE_MIN_INTERVAL", "0")
os.environ.setdefault("IMOBILIARE_JITTER", "0")
os.environ.setdefault("IMOBILIARE_BACKOFF", "0")

# Assigned, not `setdefault`: a developer with a real bucket in their shell
# would otherwise have the suite upload test reports to it. `test_storage.py`
# sets it per-test through monkeypatch, which restores this afterwards.
os.environ["IMOBILIARE_REPORTS_BUCKET"] = ""

from gemini_act.config import Settings, get_settings  # noqa: E402
from gemini_act.oauth.store import InMemoryTokenStore, TokenService  # noqa: E402
from imobiliare.config import Settings as ImobiliareSettings  # noqa: E402

# Settings reads `.env` from the working directory, so without this the suite
# asserts against whatever the developer happens to have configured locally —
# a machine with GEMINI_ACT_MCP_ENABLED trimmed for latency, say, silently tests
# a different agent than CI does. The env vars set above still apply.
Settings.model_config["env_file"] = None
# Idem pentru setările pachetului `imobiliare`, care sunt separate de cele de mai sus.
ImobiliareSettings.model_config["env_file"] = None


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def token_store() -> InMemoryTokenStore:
    return InMemoryTokenStore()


@pytest.fixture
def token_service(token_store: InMemoryTokenStore, settings: Settings) -> TokenService:
    return TokenService(token_store, settings)


@pytest.fixture(autouse=True)
def _clear_caches():
    """Keep lru_cache'd singletons from leaking between tests."""
    yield
    from gemini_act.oauth.store import get_token_service

    get_token_service.cache_clear()


@pytest.fixture(autouse=True)
def _clean_throttle_memo():
    """Nothing memoised may cross a test boundary.

    `throttle` deliberately remembers listing records and photographs for the
    life of the *process*, which is exactly what a test session is. Without
    this, the second test to ask for https://img/0.jpg gets the first test's
    bytes and passes for the wrong reason.
    """
    from imobiliare.mcp import throttle

    throttle.forget_all()
    yield
    throttle.forget_all()
