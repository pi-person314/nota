"""Shared helpers for route blueprints: session-based auth guards and a
consistent JSON error shape used across the whole HTTP API.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from flask import jsonify, session

from .. import db as db_module
from .. import models


def error_response(status: int, code: str, message: str):
    """Build the standard `{"error": CODE, "message": ...}` JSON error body."""
    return jsonify({"error": code, "message": message}), status


def current_user_id() -> str | None:
    """Return the logged-in user's id from the session cookie, or None."""
    return session.get("user_id")


def current_user() -> models.User | None:
    """Return the ORM row for the logged-in session user, or None if there
    is no session or the referenced user no longer exists.

    The returned object is detached from its session (already committed,
    with all scalar columns loaded) so callers may read its attributes
    freely; it should not be used to lazily load relationships.
    """
    user_id = current_user_id()
    if not user_id:
        return None
    with db_module.session_scope() as db_session:
        return db_session.get(models.User, user_id)


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that rejects unauthenticated requests with a 401 before
    the wrapped view runs.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user_id():
            return error_response(401, "UNAUTHENTICATED", "Login required.")
        return view(*args, **kwargs)

    return wrapped
