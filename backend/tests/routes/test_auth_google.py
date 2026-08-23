"""Tests for Google OAuth sign-in (/api/auth/google, /api/auth/google/callback)."""

from __future__ import annotations

import httpx
import pytest

from nota.routes import auth as auth_routes


@pytest.fixture
def google_env(monkeypatch):
    """Configure GOOGLE_CLIENT_ID/SECRET so /api/auth/google treats the
    integration as enabled. Individual tests can further monkeypatch
    GOOGLE_REDIRECT_URI.
    """
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")


def _fake_verified_profile(email="newgoogle@example.com", name="Gil Google"):
    return {"email": email, "email_verified": True, "name": name}


def test_google_login_redirects_to_login_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

    resp = client.get("/api/auth/google")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login?error=google_not_configured"


def test_google_login_redirects_to_google_with_state(client, google_env):
    resp = client.get("/api/auth/google")
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-client-id" in location
    assert "state=" in location
    assert "redirect_uri=" in location

    with client.session_transaction() as sess:
        assert sess.get("oauth_state")
        state_in_session = sess["oauth_state"]
    assert f"state={state_in_session}" in location


def test_callback_missing_state_is_error_and_no_user(client, app, google_env):
    resp = client.get("/api/auth/google/callback?code=somecode&state=bogus")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login?error=google_auth_failed"

    me = client.get("/api/auth/me")
    assert me.status_code == 401

    from nota import db as db_module
    from nota import models

    with db_module.session_scope() as db_session:
        assert db_session.query(models.User).count() == 0


def test_callback_wrong_state_does_not_consume_valid_session_state(client, google_env):
    # Start a real flow to populate session state, then hit the callback
    # with a mismatched state value.
    client.get("/api/auth/google")
    resp = client.get("/api/auth/google/callback?code=somecode&state=not-the-real-state")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login?error=google_auth_failed"


def test_callback_happy_path_creates_user_and_logs_in(client, google_env, monkeypatch):
    login_resp = client.get("/api/auth/google")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]

    monkeypatch.setattr(
        auth_routes,
        "_exchange_code",
        lambda code, redirect_uri, client_id, client_secret: {"access_token": "fake-token"},
    )
    monkeypatch.setattr(
        auth_routes,
        "_fetch_userinfo",
        lambda access_token: _fake_verified_profile(),
    )

    resp = client.get(f"/api/auth/google/callback?code=abc123&state={state}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/dashboard"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.get_json()
    assert body["email"] == "newgoogle@example.com"
    assert body["name"] == "Gil Google"

    from nota import db as db_module
    from nota import models

    with db_module.session_scope() as db_session:
        user = db_session.query(models.User).filter_by(email="newgoogle@example.com").first()
        assert user is not None
        assert user.password_hash is None


def test_callback_existing_password_user_logs_into_same_account(
    client, google_env, monkeypatch, signup
):
    created = signup(name="Ada", email="ada@example.com", password="hunter2pass")
    client.post("/api/auth/logout")

    client.get("/api/auth/google")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]

    monkeypatch.setattr(
        auth_routes,
        "_exchange_code",
        lambda code, redirect_uri, client_id, client_secret: {"access_token": "fake-token"},
    )
    monkeypatch.setattr(
        auth_routes,
        "_fetch_userinfo",
        lambda access_token: _fake_verified_profile(email="ada@example.com", name="Ada Google"),
    )

    resp = client.get(f"/api/auth/google/callback?code=abc123&state={state}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/dashboard"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.get_json()["id"] == created["id"]

    from nota import db as db_module
    from nota import models

    with db_module.session_scope() as db_session:
        assert db_session.query(models.User).filter_by(email="ada@example.com").count() == 1


def test_callback_unverified_email_is_rejected(client, google_env, monkeypatch):
    client.get("/api/auth/google")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]

    monkeypatch.setattr(
        auth_routes,
        "_exchange_code",
        lambda code, redirect_uri, client_id, client_secret: {"access_token": "fake-token"},
    )
    monkeypatch.setattr(
        auth_routes,
        "_fetch_userinfo",
        lambda access_token: {
            "email": "unverified@example.com",
            "email_verified": False,
            "name": "Nope",
        },
    )

    resp = client.get(f"/api/auth/google/callback?code=abc123&state={state}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login?error=google_auth_failed"

    me = client.get("/api/auth/me")
    assert me.status_code == 401

    from nota import db as db_module
    from nota import models

    with db_module.session_scope() as db_session:
        assert db_session.query(models.User).filter_by(email="unverified@example.com").count() == 0


def test_callback_exchange_error_redirects_without_crashing(client, google_env, monkeypatch):
    client.get("/api/auth/google")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]

    def _boom(code, redirect_uri, client_id, client_secret):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(auth_routes, "_exchange_code", _boom)

    resp = client.get(f"/api/auth/google/callback?code=abc123&state={state}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login?error=google_auth_failed"

    me = client.get("/api/auth/me")
    assert me.status_code == 401


def test_callback_google_error_param_redirects(client, google_env):
    client.get("/api/auth/google")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]

    resp = client.get(f"/api/auth/google/callback?error=access_denied&state={state}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login?error=google_auth_failed"
