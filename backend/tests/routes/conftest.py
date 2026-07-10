"""Extra fixtures for the route test suite: authenticated test clients and
an upload helper. Builds on the `app`/`client` fixtures from
tests/conftest.py (pytest auto-discovers parent conftest files).
"""

from __future__ import annotations

import io

import pytest

from fixtures.musicxml_builders import simple_score_bytes


@pytest.fixture
def signup(client):
    """Factory fixture: signup(name, email, password) -> response JSON.
    Leaves the returned client logged in as the new user (session cookie
    is retained by the Flask test client across requests).
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
def second_auth_client(app, signup):
    """A second, independent test client logged in as a different user —
    for ownership/cross-user access tests. Uses a separate test client
    instance so its session cookie doesn't clobber `auth_client`'s.
    """
    other_client = app.test_client()
    resp = other_client.post(
        "/api/auth/signup",
        json={"name": "Bea", "email": "bea@example.com", "password": "hunter2pass"},
    )
    assert resp.status_code == 201, resp.get_json()
    return other_client


def upload_score(client, filename="test.musicxml", content: bytes | None = None):
    """Upload a simple valid score through `client` and return the parsed
    JSON response body (a ScoreSummary).
    """
    if content is None:
        content = simple_score_bytes()
    resp = client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()
