"""The HTTP surface, exercised through a real client."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gemini_act.chat import auth
from gemini_act.chat.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_healthz(client: TestClient):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_oauth_routes_are_mounted(client: TestClient):
    """The router is included lazily, so confirm it against a live request."""
    response = client.get("/oauth/start", params={"state": "not-a-valid-state"})
    assert response.status_code == 400  # reached the handler, rejected the state


def test_oauth_start_redirects_to_google(client: TestClient):
    from gemini_act.config import get_settings
    from gemini_act.oauth.routes import make_state

    state = make_state("users/123", "spaces/AAA", get_settings())
    response = client.get("/oauth/start", params={"state": state}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")


def test_webhook_rejects_unsigned_request_when_verification_is_on(monkeypatch):
    """The deployed configuration must not accept an unsigned POST."""
    from gemini_act.config import Settings

    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: Settings(
            verify_chat_requests=True,
            chat_audience="https://svc.example.com",
            token_store="memory",
        ),
    )
    with TestClient(app) as client:
        response = client.post("/", json={"type": "MESSAGE"})
    assert response.status_code == 401


def test_webhook_handles_added_to_space(client: TestClient):
    response = client.post("/", json={"type": "ADDED_TO_SPACE"})
    assert response.status_code == 200
    assert response.json()["cardsV2"][0]["cardId"] == "welcome"
