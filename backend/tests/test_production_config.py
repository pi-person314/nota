"""Production-mode config: APP_ENV=production hardens session cookies
(Secure, in addition to the HttpOnly/SameSite=Lax set unconditionally) and
turns off the dev-only wide-open CORS handler, since the SPA is served
same-origin by this same process in production.
"""

from __future__ import annotations

import pytest

from nota import create_app
from nota.config import load_config


def _env(tmp_path, **overrides):
    db_path = tmp_path / "test.db"
    storage_dir = tmp_path / "scores"
    env = {
        "SECRET_KEY": "test-secret-key",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "SCORE_STORAGE_DIR": str(storage_dir),
        "MAX_UPLOAD_MB": "10",
        "PORT": "5001",
    }
    env.update(overrides)
    return env


def test_app_env_defaults_to_development():
    cfg = load_config({"SECRET_KEY": "x"})
    assert cfg.app_env == "development"
    assert cfg.is_production is False


def test_app_env_production_is_recognized():
    cfg = load_config({"SECRET_KEY": "x", "APP_ENV": "production"})
    assert cfg.is_production is True


def test_cookie_flags_always_set(tmp_path):
    app = create_app(_env(tmp_path))
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_development_does_not_set_secure_cookie(tmp_path):
    app = create_app(_env(tmp_path))
    assert "SESSION_COOKIE_SECURE" not in app.config or app.config["SESSION_COOKIE_SECURE"] is not True


def test_production_sets_secure_cookie(tmp_path):
    app = create_app(_env(tmp_path, APP_ENV="production"))
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_development_sends_cors_headers(tmp_path):
    app = create_app(_env(tmp_path))
    client = app.test_client()
    resp = client.get("/api/auth/me", headers={"Origin": "http://localhost:5173"})
    assert "Access-Control-Allow-Origin" in resp.headers


def test_production_does_not_send_cors_headers(tmp_path):
    app = create_app(_env(tmp_path, APP_ENV="production"))
    client = app.test_client()
    resp = client.get("/api/auth/me", headers={"Origin": "http://localhost:5173"})
    assert "Access-Control-Allow-Origin" not in resp.headers
