"""Token storage, refresh, and the consent flow's signed state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from gemini_act.config import Settings
from gemini_act.oauth import routes
from gemini_act.oauth.store import InMemoryTokenStore, StoredToken


def _token(**overrides) -> StoredToken:
    base = {
        "refresh_token": "refresh-abc",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
        "email": "ada@example.com",
        "access_token": "access-1",
        "expiry": datetime.now(UTC) + timedelta(hours=1),
    }
    return StoredToken(**{**base, **overrides})


def test_fresh_token_is_reused():
    assert _token().is_fresh() is True


def test_token_expiring_within_skew_is_stale():
    """Tokens are refreshed early so they cannot expire mid tool-call."""
    assert _token(expiry=datetime.now(UTC) + timedelta(minutes=2)).is_fresh() is False


def test_token_without_expiry_is_stale():
    assert _token(expiry=None).is_fresh() is False


def test_round_trips_through_serialization():
    original = _token()
    restored = StoredToken.from_dict(original.to_dict())
    assert restored.refresh_token == original.refresh_token
    assert restored.scopes == original.scopes
    assert restored.expiry == original.expiry


def test_has_scopes():
    token = _token(scopes=["a", "b"])
    assert token.has_scopes(("a",)) is True
    assert token.has_scopes(("a", "c")) is False


async def test_get_access_token_returns_none_for_unknown_user(token_service):
    assert await token_service.get_access_token("users/nobody") is None


async def test_get_access_token_uses_cached_token(token_service):
    await token_service.store.put("users/1", _token())
    assert await token_service.get_access_token("users/1") == "access-1"


async def test_expired_token_is_refreshed_and_persisted(token_service, monkeypatch):
    await token_service.store.put("users/1", _token(access_token="old", expiry=None))

    def fake_refresh(stored: StoredToken) -> StoredToken:
        return StoredToken(
            refresh_token=stored.refresh_token,
            scopes=stored.scopes,
            email=stored.email,
            access_token="fresh-token",
            expiry=datetime.now(UTC) + timedelta(hours=1),
        )

    monkeypatch.setattr(token_service, "_refresh", fake_refresh)

    assert await token_service.get_access_token("users/1") == "fresh-token"
    # And the refreshed value is written back, so the next call is free.
    stored = await token_service.store.get("users/1")
    assert stored.access_token == "fresh-token"


async def test_refresh_failure_yields_none_rather_than_raising(token_service, monkeypatch):
    await token_service.store.put("users/1", _token(expiry=None))

    def boom(stored):
        raise RuntimeError("refresh token revoked")

    monkeypatch.setattr(token_service, "_refresh", boom)
    assert await token_service.get_access_token("users/1") is None


async def test_concurrent_refreshes_happen_once(token_service, monkeypatch):
    import asyncio

    await token_service.store.put("users/1", _token(expiry=None))
    calls = 0

    def counting_refresh(stored):
        nonlocal calls
        calls += 1
        return StoredToken(
            refresh_token=stored.refresh_token,
            scopes=stored.scopes,
            access_token="fresh",
            expiry=datetime.now(UTC) + timedelta(hours=1),
        )

    monkeypatch.setattr(token_service, "_refresh", counting_refresh)
    results = await asyncio.gather(*(token_service.get_access_token("users/1") for _ in range(5)))

    assert results == ["fresh"] * 5
    assert calls == 1, "the per-user lock should collapse concurrent refreshes"


async def test_delete_removes_credentials():
    store = InMemoryTokenStore()
    await store.put("users/1", _token())
    await store.delete("users/1")
    assert await store.get("users/1") is None


# --- consent flow state ---


def _settings() -> Settings:
    return Settings(
        state_secret="test-secret",
        public_base_url="https://svc.example.com",
        oauth_client_id="cid",
        oauth_client_secret="secret",
        token_store="memory",
    )


def test_state_round_trips():
    settings = _settings()
    state = routes.make_state("users/123", "spaces/AAA", settings)
    assert routes.read_state(state, settings) == {
        "user_id": "users/123",
        "space": "spaces/AAA",
    }


def test_state_signed_with_another_secret_is_rejected():
    forged = routes.make_state("users/evil", "spaces/AAA", Settings(state_secret="other"))
    with pytest.raises(HTTPException) as exc:
        routes.read_state(forged, _settings())
    assert exc.value.status_code == 400


def test_tampered_state_is_rejected():
    settings = _settings()
    state = routes.make_state("users/123", "spaces/AAA", settings)
    with pytest.raises(HTTPException):
        routes.read_state(state[:-3] + "xyz", settings)


def test_authorization_url_requests_offline_consent():
    url = routes.authorization_url("users/123", "spaces/AAA", _settings())
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "redirect_uri=https%3A%2F%2Fsvc.example.com%2Foauth%2Fcallback" in url


def test_redirect_uri_derives_from_base_url():
    assert _settings().oauth_redirect_uri == "https://svc.example.com/oauth/callback"


# --- granted scopes are captured, not silently dropped ---


class _Flow:
    def __init__(self, scope):
        self.oauth2session = type("S", (), {"token": {"scope": scope}})()


class _Creds:
    def __init__(self, scopes=None):
        self.scopes = scopes


def test_granted_scopes_prefers_credentials_when_populated():
    creds = _Creds(["https://www.googleapis.com/auth/gmail.readonly"])
    assert routes._granted_scopes(_Flow(""), creds) == [
        "https://www.googleapis.com/auth/gmail.readonly"
    ]


def test_granted_scopes_falls_back_to_raw_token_response():
    """The flow is built with scopes=None, so credentials.scopes comes back
    empty and the granted set must be read off the token response."""
    flow = _Flow("openid https://www.googleapis.com/auth/gmail.readonly")
    assert routes._granted_scopes(flow, _Creds(None)) == [
        "openid",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]


def test_granted_scopes_handles_list_form():
    assert routes._granted_scopes(_Flow(["a", "b"]), _Creds(None)) == ["a", "b"]


def test_granted_scopes_empty_when_nothing_available():
    assert routes._granted_scopes(_Flow(""), _Creds(None)) == []


async def test_refresh_omits_empty_scopes(token_service, monkeypatch):
    """Passing scopes=[] would ask Google to narrow the grant to nothing."""
    captured = {}

    class FakeCredentials:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.token = "new"
            self.refresh_token = kwargs.get("refresh_token")
            self.expiry = None

        def refresh(self, request):
            return None

    monkeypatch.setattr("gemini_act.oauth.store.Credentials", FakeCredentials)
    monkeypatch.setattr("gemini_act.oauth.store.GoogleAuthRequest", lambda: object())

    token_service._refresh(_token(scopes=[], expiry=None))

    assert captured["scopes"] is None
