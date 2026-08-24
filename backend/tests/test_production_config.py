"""Production-mode config: APP_ENV=production hardens session cookies
(Secure, in addition to the HttpOnly/SameSite=Lax set unconditionally) and
turns off the dev-only wide-open CORS handler, since the SPA is served
same-origin by this same process in production.
"""

from __future__ import annotations

import io

import pytest

from nota import create_app
from nota.config import MAX_AUDIO_BYTES, ConfigError, load_config


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


def test_app_env_production_is_recognized(tmp_path):
    cfg = load_config(_env(tmp_path, APP_ENV="production"))
    assert cfg.is_production is True


def test_production_rejects_relative_database_path(tmp_path):
    # The default DATABASE_URL is relative, which in a container resolves
    # inside the image rather than on the mounted volume.
    env = _env(tmp_path, APP_ENV="production")
    env["DATABASE_URL"] = "sqlite:///nota.db"

    with pytest.raises(ConfigError) as excinfo:
        load_config(env)
    assert "DATABASE_URL" in str(excinfo.value)


def test_production_rejects_relative_score_storage_dir(tmp_path):
    env = _env(tmp_path, APP_ENV="production")
    env["SCORE_STORAGE_DIR"] = "./data/scores"

    with pytest.raises(ConfigError) as excinfo:
        load_config(env)
    assert "SCORE_STORAGE_DIR" in str(excinfo.value)


def test_production_accepts_non_sqlite_database_url(tmp_path):
    # A PostgreSQL URL has no local filesystem path to be relative.
    env = _env(tmp_path, APP_ENV="production")
    env["DATABASE_URL"] = "postgresql://user:pw@db.example.com:5432/nota"

    cfg = load_config(env)
    assert cfg.database_url.startswith("postgresql://")


def test_development_allows_relative_paths():
    # Relative paths are the normal, convenient default outside production.
    cfg = load_config({"SECRET_KEY": "x"})
    assert cfg.database_url == "sqlite:///nota.db"
    assert cfg.score_storage_dir == "./data/scores"


def test_request_ceiling_accommodates_the_largest_route_limit(tmp_path):
    # Audio (25 MB) is larger than a small MAX_UPLOAD_MB, so the ceiling
    # must be driven by the largest limit, not by the score-upload one, or
    # transcription of a long recording would be blocked before its own
    # route could answer for it.
    cfg = load_config(_env(tmp_path, MAX_UPLOAD_MB="5"))
    assert cfg.max_request_bytes > MAX_AUDIO_BYTES

    cfg = load_config(_env(tmp_path, MAX_UPLOAD_MB="100"))
    assert cfg.max_request_bytes > cfg.max_upload_bytes


def test_oversized_request_body_is_rejected_as_json(tmp_path):
    app = create_app(_env(tmp_path))
    client = app.test_client()
    # The upload route is login-gated, and that check runs before the body
    # is parsed — so an unauthenticated request would 401 long before the
    # size ceiling could be exercised.
    client.post(
        "/api/auth/signup",
        json={"name": "Ada", "email": "ada@example.com", "password": "hunter2pass"},
    )

    resp = client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(b"x" * (app.config["MAX_CONTENT_LENGTH"] + 1)), "huge.musicxml")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 413
    assert resp.get_json()["error"] == "FILE_TOO_LARGE"


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


def test_posix_container_paths_accepted_regardless_of_host_platform(tmp_path):
    """A deployment's data paths describe a Linux container, even when the
    tests run on Windows. `os.path.isabs` follows the host's rules and
    rejects "/data" on Windows, so the check must not defer to it.
    """
    env = _env(tmp_path, APP_ENV="production")
    env["DATABASE_URL"] = "sqlite:////data/nota.db"
    env["SCORE_STORAGE_DIR"] = "/data/scores"

    cfg = load_config(env)
    assert cfg.database_url == "sqlite:////data/nota.db"
    assert cfg.score_storage_dir == "/data/scores"
