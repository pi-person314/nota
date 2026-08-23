"""SPA serving: when FRONTEND_DIST_DIR is configured, Flask serves the
built frontend directly — static files as-is, unknown non-API paths
falling back to index.html for client-side routing, and /api paths never
falling back. With FRONTEND_DIST_DIR unset (the tests/conftest.py `app`
fixture), none of this routing exists and prior behavior is unchanged.
"""

from __future__ import annotations

import pytest

from nota import create_app


@pytest.fixture
def dist_dir(tmp_path):
    """A fake built-frontend directory: an index.html "shell" and a
    content-hashed asset under assets/, matching what `vite build` produces.
    """
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)

    (dist / "index.html").write_text("<html><body>spa shell</body></html>", encoding="utf-8")
    (assets / "index-abc123.js").write_text("console.log('hi');", encoding="utf-8")

    return dist


@pytest.fixture
def spa_app(tmp_path, dist_dir):
    db_path = tmp_path / "test.db"
    storage_dir = tmp_path / "scores"

    env = {
        "SECRET_KEY": "test-secret-key",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "SCORE_STORAGE_DIR": str(storage_dir),
        "MAX_UPLOAD_MB": "10",
        "PORT": "5001",
        "FRONTEND_DIST_DIR": str(dist_dir),
    }

    flask_app = create_app(env)
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def spa_client(spa_app):
    return spa_app.test_client()


def test_root_serves_index_html(spa_client):
    resp = spa_client.get("/")
    assert resp.status_code == 200
    assert b"spa shell" in resp.data


def test_client_side_route_falls_back_to_index_html(spa_client):
    resp = spa_client.get("/dashboard")
    assert resp.status_code == 200
    assert b"spa shell" in resp.data


def test_client_side_route_with_query_string_falls_back_to_index_html(spa_client):
    resp = spa_client.get("/reset-password?token=abc123")
    assert resp.status_code == 200
    assert b"spa shell" in resp.data


def test_existing_asset_is_served_with_immutable_cache_header(spa_client):
    resp = spa_client.get("/assets/index-abc123.js")
    assert resp.status_code == 200
    assert b"console.log" in resp.data
    assert resp.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_index_html_response_has_no_cache_header(spa_client):
    resp = spa_client.get("/")
    assert resp.headers["Cache-Control"] == "no-cache"

    resp = spa_client.get("/dashboard")
    assert resp.headers["Cache-Control"] == "no-cache"


def test_unknown_api_path_does_not_fall_back_to_index_html(spa_client):
    resp = spa_client.get("/api/definitely-not-a-route")
    assert resp.status_code == 404
    assert b"spa shell" not in resp.data


def test_real_api_route_still_works_alongside_spa_serving(spa_client):
    resp = spa_client.post(
        "/api/auth/signup",
        json={"name": "Ada", "email": "ada@example.com", "password": "hunter2pass"},
    )
    assert resp.status_code == 201


def test_frontend_dist_dir_unset_behaves_as_before(client):
    """The plain `client` fixture (tests/conftest.py) has no
    FRONTEND_DIST_DIR set, so there's no catch-all route at all: an
    unmatched path is a plain 404, not an index.html fallback.
    """
    resp = client.get("/dashboard")
    assert resp.status_code == 404

    resp = client.get("/")
    assert resp.status_code == 404
