"""Flask application factory for the Nota backend."""

from __future__ import annotations

import importlib
import logging

from flask import Flask, abort, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import NotFound, RequestEntityTooLarge

from . import conversion
from . import db as db_module
from . import storage
from .config import load_config

logger = logging.getLogger(__name__)


def create_app(env: dict | None = None) -> Flask:
    """Build and configure the Flask application.

    `env` optionally overrides the environment mapping used to read
    configuration (used by tests to point at a temporary database and
    storage directory without touching real process environment
    variables). Defaults to `os.environ`.
    """
    cfg = load_config(env)

    app = Flask(__name__)
    app.config["SECRET_KEY"] = cfg.secret_key
    app.config["NOTA_CONFIG"] = cfg

    # SESSION_COOKIE_SAMESITE="Lax" is correct (rather than "Strict") because
    # the Google OAuth callback returns the browser to us via a top-level GET
    # navigation initiated by Google's site, not by ours; "Lax" still sends
    # the session cookie on that navigation while "Strict" would drop it and
    # break login. SESSION_COOKIE_SECURE additionally requires HTTPS, which
    # only holds once we're actually deployed behind TLS.
    # Refuse an oversized request body while it is still streaming in,
    # rather than after Werkzeug has buffered the whole thing into memory
    # for a route to measure and reject. Routes keep their own tighter
    # limits; this is the backstop that keeps a single huge upload from
    # exhausting a small instance's memory.
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_request_bytes

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if cfg.is_production:
        app.config["SESSION_COOKIE_SECURE"] = True

    # In production the built SPA is served by this same app (same origin),
    # so cross-origin credentialed requests are not a legitimate use case —
    # CORS here is purely a convenience for `vite dev` running on its own
    # port. Registering it in production would needlessly widen the attack
    # surface for a mechanism nothing actually needs.
    if not cfg.is_production:
        # The frontend authenticates via session cookies, so credentialed
        # requests (cookies) must be allowed across the dev origin boundary.
        CORS(app, supports_credentials=True)

    db_module.init_db(cfg.database_url)
    storage.configure(database_url=cfg.database_url, score_storage_dir=cfg.score_storage_dir)

    # Clean up any PDF conversion left stranded `queued`/`running` by a
    # previous process life (the in-process worker pool that runs them
    # doesn't survive a restart). Best-effort: a failure here is logged,
    # never allowed to stop the app from starting.
    try:
        conversion.reconcile_interrupted_jobs()
    except Exception:
        logger.exception("Failed to reconcile interrupted conversion jobs at startup.")

    _register_blueprints(app)

    if cfg.frontend_dist_dir:
        _register_spa(app, cfg.frontend_dist_dir)

    @app.errorhandler(RequestEntityTooLarge)
    def _too_large(_exc):
        # Werkzeug's own 413 is an HTML page; every other error this API
        # returns is JSON in the {"error": CODE, "message": ...} shape the
        # frontend knows how to read, so this one matches.
        return (
            jsonify(
                {
                    "error": "FILE_TOO_LARGE",
                    "message": (
                        f"Request exceeds the {cfg.max_request_bytes // (1024 * 1024)} MB limit."
                    ),
                }
            ),
            413,
        )

    return app


def _register_blueprints(app: Flask) -> None:
    """Register route blueprints, if the routes package exists.

    Route modules are added separately from this shared foundation; the
    import is guarded so the app factory works standalone before any
    routes have been added. Once `nota/routes/__init__.py` exists and
    exposes a `register_blueprints(app)` function, it will be picked up
    automatically.
    """
    try:
        routes_pkg = importlib.import_module(".routes", __name__)
    except ImportError:
        return

    register = getattr(routes_pkg, "register_blueprints", None)
    if callable(register):
        register(app)


def _register_spa(app: Flask, dist_dir: str) -> None:
    """Serve the built frontend SPA from `dist_dir` for single-instance
    deployment, where this Flask process is the only thing in front of the
    browser (no separate static host or CDN).

    A GET request for an existing file under `dist_dir` gets that file.
    Hashed build assets under `assets/` (Vite content-hashes their
    filenames) are safe to cache forever; `index.html` is marked no-cache
    so a new deploy takes effect on the next load instead of being pinned
    by a stale cached shell. Any other GET path that isn't under `/api`
    falls back to `index.html` so client-side routes (e.g. `/dashboard`)
    resolve correctly on a cold load/refresh. `/api/...` paths are never
    served the SPA fallback; an unmatched one stays a normal 404.
    """

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_spa(path: str):
        if path == "api" or path.startswith("api/"):
            abort(404)

        if path:
            try:
                # send_from_directory safely resolves `path` against
                # dist_dir (rejecting traversal) and raises NotFound if it
                # doesn't land on an existing regular file.
                response = send_from_directory(dist_dir, path)
            except NotFound:
                response = None
            if response is not None:
                if path.startswith("assets/"):
                    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return response

        response = send_from_directory(dist_dir, "index.html")
        response.headers["Cache-Control"] = "no-cache"
        return response
