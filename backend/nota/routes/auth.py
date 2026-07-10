"""Authentication routes: signup, login, logout, and the current session user.

Sessions are Flask's signed cookie sessions (no server-side session store);
the cookie holds only the user id, and `SECRET_KEY` (required config) signs
it. Passwords are hashed with bcrypt and never stored or returned in plain
text.
"""

from __future__ import annotations

import bcrypt
from flask import Blueprint, jsonify, request, session

from .. import db as db_module
from .. import models
from ._helpers import current_user, error_response, login_required

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _user_summary(user: models.User) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email}


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _check_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed stored hash; treat as a non-match rather than a 500.
        return False


@bp.post("/signup")
def signup():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or not password:
        return error_response(
            422, "INVALID_INPUT", "name, email, and password are all required."
        )

    with db_module.session_scope() as db_session:
        existing = db_session.query(models.User).filter_by(email=email).first()
        if existing is not None:
            return error_response(
                409, "EMAIL_TAKEN", "An account with that email already exists."
            )

        user = models.User(name=name, email=email, password_hash=_hash_password(password))
        db_session.add(user)
        db_session.flush()
        user_id = user.id
        summary = _user_summary(user)

    session["user_id"] = user_id
    return jsonify(summary), 201


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    with db_module.session_scope() as db_session:
        user = db_session.query(models.User).filter_by(email=email).first()
        if user is None or not user.password_hash or not _check_password(
            password, user.password_hash
        ):
            return error_response(
                401, "INVALID_CREDENTIALS", "Incorrect email or password."
            )
        user_id = user.id
        summary = _user_summary(user)

    session["user_id"] = user_id
    return jsonify(summary), 200


@bp.post("/logout")
def logout():
    session.pop("user_id", None)
    return jsonify({"ok": True}), 200


@bp.get("/me")
@login_required
def me():
    user = current_user()
    if user is None:
        # The session cookie references a user that no longer exists
        # (e.g. deleted account); clear it rather than pretend they're
        # logged in.
        session.pop("user_id", None)
        return error_response(401, "UNAUTHENTICATED", "Login required.")
    return jsonify(_user_summary(user)), 200
