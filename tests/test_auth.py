"""Verification of Chat-signed requests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from gemini_act.chat import auth
from gemini_act.config import Settings


class _Verifier:
    """Stand-in for google.oauth2.id_token.verify_oauth2_token."""

    def __init__(self, claims: dict | Exception):
        self.claims = claims
        self.calls: list[tuple[str, str]] = []

    def __call__(self, token, request, audience):
        self.calls.append((token, audience))
        if isinstance(self.claims, Exception):
            raise self.claims
        return self.claims


async def test_accepts_token_from_chat_issuer(monkeypatch):
    verifier = _Verifier({"email": auth.CHAT_ISSUER})
    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", verifier)

    assert await auth.verify_chat_token("tok", "https://svc.example.com") is True
    assert verifier.calls == [("tok", "https://svc.example.com")]


async def test_rejects_token_from_other_issuer(monkeypatch):
    monkeypatch.setattr(
        auth.id_token, "verify_oauth2_token", _Verifier({"email": "attacker@evil.example"})
    )
    assert await auth.verify_chat_token("tok", "https://svc.example.com") is False


async def test_rejects_unverifiable_token(monkeypatch):
    monkeypatch.setattr(
        auth.id_token, "verify_oauth2_token", _Verifier(ValueError("bad signature"))
    )
    assert await auth.verify_chat_token("tok", "https://svc.example.com") is False


def _verifying_settings(**overrides) -> Settings:
    base = {
        "verify_chat_requests": True,
        "chat_audience": "https://svc.example.com",
        "token_store": "memory",
    }
    return Settings(**{**base, **overrides})


async def test_dependency_rejects_missing_header(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", _verifying_settings)
    with pytest.raises(HTTPException) as exc:
        await auth.require_chat_request(authorization=None)
    assert exc.value.status_code == 401


async def test_dependency_rejects_non_bearer_header(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", _verifying_settings)
    with pytest.raises(HTTPException) as exc:
        await auth.require_chat_request(authorization="Basic abc123")
    assert exc.value.status_code == 401


async def test_dependency_rejects_forged_token(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", _verifying_settings)
    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", _Verifier(ValueError("nope")))
    with pytest.raises(HTTPException) as exc:
        await auth.require_chat_request(authorization="Bearer forged")
    assert exc.value.status_code == 401


async def test_dependency_accepts_valid_token(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", _verifying_settings)
    monkeypatch.setattr(
        auth.id_token, "verify_oauth2_token", _Verifier({"email": auth.CHAT_ISSUER})
    )
    assert await auth.require_chat_request(authorization="Bearer good") is None


async def test_fails_closed_when_audience_unset(monkeypatch):
    """No audience means nothing can be verified — reject rather than wave through."""
    monkeypatch.setattr(auth, "get_settings", lambda: _verifying_settings(chat_audience=""))
    with pytest.raises(HTTPException) as exc:
        await auth.require_chat_request(authorization="Bearer whatever")
    assert exc.value.status_code == 500
