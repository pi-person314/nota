"""Flask application factory for the Nota backend."""

from __future__ import annotations

import importlib

from flask import Flask
from flask_cors import CORS

from . import db as db_module
from . import storage
from .config import load_config


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

    # The frontend authenticates via session cookies, so credentialed
    # requests (cookies) must be allowed across the dev origin boundary.
    CORS(app, supports_credentials=True)

    db_module.init_db(cfg.database_url)
    storage.configure(database_url=cfg.database_url, score_storage_dir=cfg.score_storage_dir)

    _register_blueprints(app)

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
