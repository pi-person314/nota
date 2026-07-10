"""Tests for signup/login/logout/me."""

from __future__ import annotations


def test_signup_creates_session_and_returns_summary(client):
    resp = client.post(
        "/api/auth/signup",
        json={"name": "Ada", "email": "ada@example.com", "password": "hunter2pass"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Ada"
    assert body["email"] == "ada@example.com"
    assert "id" in body
    assert "password" not in body
    assert "password_hash" not in body


def test_signup_missing_fields_is_422(client):
    resp = client.post("/api/auth/signup", json={"name": "Ada", "email": "ada@example.com"})
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "INVALID_INPUT"


def test_signup_duplicate_email_is_409(client):
    client.post(
        "/api/auth/signup",
        json={"name": "Ada", "email": "dup@example.com", "password": "hunter2pass"},
    )
    resp = client.post(
        "/api/auth/signup",
        json={"name": "Someone Else", "email": "dup@example.com", "password": "otherpass"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "EMAIL_TAKEN"


def test_duplicate_email_is_case_insensitive(client):
    client.post(
        "/api/auth/signup",
        json={"name": "Ada", "email": "Case@Example.com", "password": "hunter2pass"},
    )
    resp = client.post(
        "/api/auth/signup",
        json={"name": "Ada2", "email": "case@example.com", "password": "hunter2pass"},
    )
    assert resp.status_code == 409


def test_me_requires_login(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "UNAUTHENTICATED"


def test_me_returns_current_user_after_signup(client):
    client.post(
        "/api/auth/signup",
        json={"name": "Ada", "email": "ada@example.com", "password": "hunter2pass"},
    )
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.get_json()["email"] == "ada@example.com"


def test_login_with_correct_credentials(client):
    client.post(
        "/api/auth/signup",
        json={"name": "Ada", "email": "ada@example.com", "password": "hunter2pass"},
    )
    client.post("/api/auth/logout")
    resp = client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "hunter2pass"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["email"] == "ada@example.com"

    resp = client.get("/api/auth/me")
    assert resp.status_code == 200


def test_login_wrong_password_is_401(client):
    client.post(
        "/api/auth/signup",
        json={"name": "Ada", "email": "ada@example.com", "password": "hunter2pass"},
    )
    client.post("/api/auth/logout")
    resp = client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "wrongpass"}
    )
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "INVALID_CREDENTIALS"


def test_login_unknown_email_is_401(client):
    resp = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "INVALID_CREDENTIALS"


def test_logout_clears_session(client):
    client.post(
        "/api/auth/signup",
        json={"name": "Ada", "email": "ada@example.com", "password": "hunter2pass"},
    )
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200

    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
