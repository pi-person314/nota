"""Fixtures for the services test suite (Whisper transcription).

Self-contained: builds its own authenticated-client fixture rather than
importing from tests/routes/conftest.py, so this directory can run
independently. Reuses the `app`/`client` fixtures from the top-level
tests/conftest.py (pytest auto-discovers parent conftest files).
"""

from __future__ import annotations

import pytest

from nota.services import whisper

from .fakes import FakeOpenAIClient


@pytest.fixture(autouse=True)
def _reset_whisper_client_singleton():
    """Guard against test-order pollution of the service's module-level
    cached OpenAI client -- most tests monkeypatch `_get_client` directly,
    but the STT_NOT_CONFIGURED test exercises the real function, which
    caches onto a module global.
    """
    whisper._client = None
    yield
    whisper._client = None


@pytest.fixture
def signup(client):
    """Factory fixture: signup(name, email, password) -> response JSON.
    Leaves the returned client logged in (session cookie retained by the
    Flask test client across requests).
    """

    def _signup(name="Ada", email="ada@example.com", password="hunter2pass"):
        resp = client.post(
            "/api/auth/signup",
            json={"name": name, "email": email, "password": password},
        )
        assert resp.status_code == 201, resp.get_json()
        return resp.get_json()

    return _signup


@pytest.fixture
def auth_client(client, signup):
    """A test client already logged in as a fresh user."""
    signup()
    return client


@pytest.fixture
def install_fake_client(monkeypatch):
    """Factory fixture: install_fake_client(response_or_exception) ->
    FakeOpenAIClient. Monkeypatches `nota.services.whisper._get_client` so
    the service never touches the real OpenAI API.
    """

    def _install(item) -> FakeOpenAIClient:
        fake = FakeOpenAIClient(item)
        monkeypatch.setattr(whisper, "_get_client", lambda: fake)
        return fake

    return _install
