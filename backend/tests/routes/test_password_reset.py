"""Tests for the password-reset flow (/api/auth/forgot-password,
/api/auth/reset-password).
"""

from __future__ import annotations

import hashlib
import logging

from nota.routes import auth as auth_routes


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _request_reset(client, monkeypatch, email):
    """Trigger forgot-password and capture the raw token from the link
    handed to `_send_reset_email`, via monkeypatch. Returns the raw token,
    or None if no email was ever "sent" (unknown address).
    """
    captured = {}

    def _fake_send(to_email, link):
        captured["email"] = to_email
        captured["link"] = link

    monkeypatch.setattr(auth_routes, "_send_reset_email", _fake_send)

    resp = client.post("/api/auth/forgot-password", json={"email": email})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    if "link" not in captured:
        return None
    return captured["link"].rsplit("token=", 1)[1]


# --- forgot-password ---------------------------------------------------


def test_forgot_password_unknown_email_returns_ok_and_no_token_row(client, monkeypatch):
    monkeypatch.setattr(auth_routes, "_send_reset_email", lambda *a, **k: None)

    resp = client.post(
        "/api/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    from nota import db as db_module
    from nota import models

    with db_module.session_scope() as db_session:
        assert db_session.query(models.PasswordResetToken).count() == 0


def test_forgot_password_known_email_creates_hashed_token_and_sends_link(
    client, signup, monkeypatch
):
    signup(name="Ada", email="ada@example.com", password="hunter2pass")

    calls = []
    monkeypatch.setattr(
        auth_routes, "_send_reset_email", lambda email, link: calls.append((email, link))
    )

    resp = client.post("/api/auth/forgot-password", json={"email": "ada@example.com"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    assert len(calls) == 1
    sent_email, link = calls[0]
    assert sent_email == "ada@example.com"
    assert "/reset-password?token=" in link
    raw_token = link.rsplit("token=", 1)[1]
    assert raw_token

    from nota import db as db_module
    from nota import models

    with db_module.session_scope() as db_session:
        rows = db_session.query(models.PasswordResetToken).all()
        assert len(rows) == 1
        # The raw token is never stored — only its hash.
        assert rows[0].token_hash == _token_hash(raw_token)
        assert raw_token not in rows[0].token_hash


def test_forgot_password_blank_email_is_422(client):
    resp = client.post("/api/auth/forgot-password", json={"email": "  "})
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "INVALID_INPUT"


def test_forgot_password_logs_link_when_smtp_unconfigured(
    client, signup, monkeypatch, caplog
):
    signup(name="Ada", email="ada@example.com", password="hunter2pass")
    monkeypatch.delenv("SMTP_HOST", raising=False)

    with caplog.at_level(logging.INFO):
        resp = client.post("/api/auth/forgot-password", json={"email": "ada@example.com"})

    assert resp.status_code == 200
    assert any("Password reset link" in message for message in caplog.messages)


def test_forgot_password_smtp_failure_does_not_leak_to_client(
    client, signup, monkeypatch
):
    signup(name="Ada", email="ada@example.com", password="hunter2pass")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")

    class _BoomSMTP:
        def __init__(self, *a, **k):
            raise OSError("connection refused")

    monkeypatch.setattr(auth_routes.smtplib, "SMTP", _BoomSMTP)

    resp = client.post("/api/auth/forgot-password", json={"email": "ada@example.com"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


def test_forgot_password_response_identical_for_known_and_unknown_email(
    client, signup, monkeypatch
):
    signup(name="Ada", email="ada@example.com", password="hunter2pass")
    monkeypatch.setattr(auth_routes, "_send_reset_email", lambda *a, **k: None)

    known = client.post("/api/auth/forgot-password", json={"email": "ada@example.com"})
    unknown = client.post(
        "/api/auth/forgot-password", json={"email": "nobody@example.com"}
    )

    assert known.status_code == unknown.status_code == 200
    assert known.get_json() == unknown.get_json() == {"ok": True}


# --- reset-password ------------------------------------------------------


def test_reset_password_happy_path_changes_password(client, signup, monkeypatch):
    signup(name="Ada", email="ada@example.com", password="hunter2pass")
    client.post("/api/auth/logout")

    raw_token = _request_reset(client, monkeypatch, "ada@example.com")
    assert raw_token

    resp = client.post(
        "/api/auth/reset-password",
        json={"token": raw_token, "password": "newpassword1"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    # Resetting does not auto-login.
    me = client.get("/api/auth/me")
    assert me.status_code == 401

    # New password works, old one doesn't.
    old = client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "hunter2pass"}
    )
    assert old.status_code == 401

    new = client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "newpassword1"}
    )
    assert new.status_code == 200


def test_reset_password_invalid_token_is_422(client):
    resp = client.post(
        "/api/auth/reset-password",
        json={"token": "not-a-real-token", "password": "newpassword1"},
    )
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "INVALID_RESET_TOKEN"


def test_reset_password_expired_token_is_422(client, signup, monkeypatch):
    signup(name="Ada", email="ada@example.com", password="hunter2pass")
    raw_token = _request_reset(client, monkeypatch, "ada@example.com")

    from datetime import datetime, timedelta, timezone

    from nota import db as db_module
    from nota import models

    with db_module.session_scope() as db_session:
        row = (
            db_session.query(models.PasswordResetToken)
            .filter_by(token_hash=_token_hash(raw_token))
            .first()
        )
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    resp = client.post(
        "/api/auth/reset-password",
        json={"token": raw_token, "password": "newpassword1"},
    )
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "INVALID_RESET_TOKEN"


def test_reset_password_reused_token_is_422(client, signup, monkeypatch):
    signup(name="Ada", email="ada@example.com", password="hunter2pass")
    raw_token = _request_reset(client, monkeypatch, "ada@example.com")

    first = client.post(
        "/api/auth/reset-password",
        json={"token": raw_token, "password": "newpassword1"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/auth/reset-password",
        json={"token": raw_token, "password": "anotherpass2"},
    )
    assert second.status_code == 422
    assert second.get_json()["error"] == "INVALID_RESET_TOKEN"


def test_reset_password_weak_password_is_signup_rule_error(client, signup, monkeypatch):
    signup(name="Ada", email="ada@example.com", password="hunter2pass")
    raw_token = _request_reset(client, monkeypatch, "ada@example.com")

    resp = client.post(
        "/api/auth/reset-password",
        json={"token": raw_token, "password": "short"},
    )
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "INVALID_INPUT"
    assert "8 characters" in resp.get_json()["message"]
