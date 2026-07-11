"""Route blueprints for the Nota HTTP API.

`nota.create_app` imports this package and calls `register_blueprints`
if it's present (see `nota/__init__.py`), so nothing else needs to wire
these up.
"""

from __future__ import annotations

from flask import Flask

from .auth import bp as auth_bp
from .commands import bp as commands_bp
from .scores import bp as scores_bp
from .transcribe import bp as transcribe_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(auth_bp)
    app.register_blueprint(scores_bp)
    app.register_blueprint(commands_bp)
    app.register_blueprint(transcribe_bp)
