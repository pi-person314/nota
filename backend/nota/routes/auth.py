"""Authentication routes: signup, login, logout, the current session user,
and Google OAuth sign-in.

Sessions are Flask's signed cookie sessions (no server-side session store);
the cookie holds only the user id, and `SECRET_KEY` (required config) signs
it. Passwords are hashed with bcrypt and never stored or returned in plain
text.

Google sign-in uses the server-side OAuth 2.0 authorization code flow:
the browser is redirected to Google, Google redirects back to us with a
one-time code, and this server (not the browser) exchanges that code for
an access token directly with Google over TLS. Because that exchange is a
direct server-to-server call to Google, the token response and the profile
it unlocks are trusted as-is; there is no ID token signature to verify
locally.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode, urlsplit

import bcrypt
import httpx
from flask import Blueprint, current_app, jsonify, redirect, request, session

from .. import db as db_module
from .. import models
from ._helpers import current_user, error_response, login_required

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_HTTP_TIMEOUT_SECONDS = 10.0
_SMTP_TIMEOUT_SECONDS = 10.0

_MIN_PASSWORD_LENGTH = 8
_RESET_TOKEN_TTL = timedelta(hours=1)


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


def _validate_password(password: str) -> str | None:
    """Return an error message if `password` doesn't meet the minimum
    strength bar, or None if it's acceptable.

    The single source of truth for password strength, shared by signup and
    password-reset so a reset can never leave an account with a password
    signup itself would have rejected.
    """
    if len(password) < _MIN_PASSWORD_LENGTH:
        return f"Password must be at least {_MIN_PASSWORD_LENGTH} characters."
    return None


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

    password_error = _validate_password(password)
    if password_error:
        return error_response(422, "INVALID_INPUT", password_error)

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


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """Normalize a datetime read back from the database to aware UTC.

    Timestamps are always written as aware UTC, but SQLite round-trips
    drop tzinfo, so values read back are naive; treat naive datetimes as
    UTC so expiry comparisons are correct regardless of backend.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _resolve_app_base_url() -> str:
    """Resolve the origin the frontend is served from, for building
    password-reset links.

    Precedence: `APP_BASE_URL` wins outright when set — the only reliable
    source in production behind a proxy that rewrites the Host header
    (same situation `_google_redirect_uri` documents above). Otherwise,
    fall back to the browser-supplied Origin or Referer header, which is
    good enough for a link that only ever appears in the requester's own
    inbox. Last resort is Flask's own `request.url_root`, correct only
    when Flask is the origin the browser talks to directly (e.g. no
    origin-rewriting proxy in front, or local dev without the Vite proxy).
    """
    configured = os.environ.get("APP_BASE_URL")
    if configured:
        return configured.rstrip("/")

    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"

    return request.url_root.rstrip("/")


def _send_reset_email(email: str, link: str) -> None:
    """Deliver the password-reset link to `email`.

    Isolated in its own function so tests can monkeypatch it to capture
    the link without a real SMTP server, and so the calling route never
    has to know whether delivery actually succeeded. Any failure here is
    logged and swallowed rather than raised: letting an SMTP outage turn
    into a 500 (or into a response that differs from the unknown-email
    case) would both break the UX and reopen the account-enumeration hole
    the caller is trying to close.

    When `SMTP_HOST` isn't configured, there is no mail server to hand the
    link to, so it's logged at INFO level instead — enough for a developer
    running the app locally to grab it straight from the console.
    """
    smtp_host = os.environ.get("SMTP_HOST")
    if not smtp_host:
        current_app.logger.info("Password reset link for %s: %s", email, link)
        return

    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_from = os.environ.get("SMTP_FROM") or smtp_username or "no-reply@nota.app"

    message = EmailMessage()
    message["Subject"] = "Reset your Nota password"
    message["From"] = smtp_from
    message["To"] = email
    message.set_content(
        "We received a request to reset your Nota password.\n\n"
        f"Reset it here: {link}\n\n"
        "This link expires in 1 hour. If you didn't request this, you can safely ignore this email."
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=_SMTP_TIMEOUT_SECONDS) as smtp:
            if smtp_port == 587:
                smtp.starttls()
            if smtp_username and smtp_password:
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
    except Exception:
        current_app.logger.exception("Failed to send password reset email to %s", email)


@bp.post("/forgot-password")
def forgot_password():
    """Request a password-reset link.

    Always responds 200 `{"ok": true}` regardless of whether the email
    belongs to an account, so the endpoint can't be used to enumerate
    registered users. Email validation is deliberately minimal (non-blank
    only): a stricter format check would itself leak information
    (well-formed-but-unknown vs malformed), for no benefit since the
    response is identical either way.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    if not email:
        return error_response(422, "INVALID_INPUT", "Email is required.")

    link = None
    with db_module.session_scope() as db_session:
        user = db_session.query(models.User).filter_by(email=email).first()
        if user is not None:
            raw_token = secrets.token_urlsafe(32)
            db_session.add(
                models.PasswordResetToken(
                    user_id=user.id,
                    token_hash=_hash_token(raw_token),
                    expires_at=_utcnow() + _RESET_TOKEN_TTL,
                )
            )
            link = f"{_resolve_app_base_url()}/reset-password?token={raw_token}"

    if link is not None:
        _send_reset_email(email, link)

    return jsonify({"ok": True}), 200


@bp.post("/reset-password")
def reset_password():
    """Complete a password reset using the token from the emailed link.

    The user is intentionally not logged in on success: proving control of
    the reset link is enough to prove ownership of the email address, but
    logging in still requires the new password, keeping "reset my
    password" and "start a session" as separate, deliberate actions.
    """
    data = request.get_json(silent=True) or {}
    token = data.get("token") or ""
    password = data.get("password") or ""

    invalid_token = error_response(
        422,
        "INVALID_RESET_TOKEN",
        "That link is invalid or has expired. Request a new one.",
    )

    if not token:
        return invalid_token

    password_error = _validate_password(password)
    if password_error:
        return error_response(422, "INVALID_INPUT", password_error)

    token_hash = _hash_token(token)
    now = _utcnow()

    with db_module.session_scope() as db_session:
        reset_token = (
            db_session.query(models.PasswordResetToken)
            .filter_by(token_hash=token_hash)
            .first()
        )
        valid = (
            reset_token is not None
            and reset_token.used_at is None
            and _as_utc(reset_token.expires_at) >= now
        )
        user = None
        if valid:
            user = db_session.get(models.User, reset_token.user_id)
            valid = user is not None

        if valid:
            user.password_hash = _hash_password(password)
            reset_token.used_at = now

    if not valid:
        return invalid_token

    return jsonify({"ok": True}), 200


def _google_redirect_uri() -> str:
    """Resolve the callback URL Google should redirect the browser back to.

    `GOOGLE_REDIRECT_URI` wins outright when set, and in local dev it must
    be set: the Vite dev proxy forwards `/api/*` to this Flask process with
    `changeOrigin: true`, which rewrites the Host header on the way in, so
    inside this process `request.url_root` reflects Flask's own address
    (e.g. http://127.0.0.1:5001/) rather than the origin the browser is
    actually on (e.g. http://localhost:5173). Registering the backend's own
    origin with Google would strand the user there after the callback,
    since only the frontend origin serves the SPA routes (like /dashboard)
    the final redirect lands on. Deriving from `request.url_root` is only
    correct when Flask itself is the origin the browser talks to directly,
    e.g. a production deployment with no origin-rewriting proxy in front.
    """
    configured = os.environ.get("GOOGLE_REDIRECT_URI")
    if configured:
        return configured
    return request.url_root + "api/auth/google/callback"


def _exchange_code(code: str, redirect_uri: str, client_id: str, client_secret: str) -> dict:
    """Exchange an authorization code for tokens at Google's token endpoint.

    Raises httpx.HTTPError (via raise_for_status) on any non-2xx response,
    and any other httpx exception on transport failures/timeouts; callers
    are expected to catch those.
    """
    resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_userinfo(access_token: str) -> dict:
    """Fetch the authenticated user's OpenID Connect profile from Google."""
    resp = httpx.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


@bp.get("/google")
def google_login():
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        # A browser navigation landed here, so a JSON 503 would strand the
        # user on a raw API response; send them back to the login page
        # with something the UI can turn into a friendly message.
        return redirect("/login?error=google_not_configured")

    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state

    params = {
        "client_id": client_id,
        "redirect_uri": _google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    }
    return redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@bp.get("/google/callback")
def google_callback():
    expected_state = session.pop("oauth_state", None)
    got_state = request.args.get("state")
    if (
        not expected_state
        or not got_state
        or not secrets.compare_digest(expected_state, got_state)
    ):
        return redirect("/login?error=google_auth_failed")

    # The user declined consent, or Google otherwise couldn't issue a code.
    if request.args.get("error"):
        return redirect("/login?error=google_auth_failed")

    code = request.args.get("code")
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not code or not client_id or not client_secret:
        return redirect("/login?error=google_auth_failed")

    try:
        token_data = _exchange_code(code, _google_redirect_uri(), client_id, client_secret)
        access_token = token_data.get("access_token")
        if not access_token:
            return redirect("/login?error=google_auth_failed")
        profile = _fetch_userinfo(access_token)
    except httpx.HTTPError:
        # Covers non-2xx responses (raise_for_status), timeouts, and
        # connection failures alike — never let a Google outage surface a
        # traceback to the browser.
        return redirect("/login?error=google_auth_failed")

    email = (profile.get("email") or "").strip().lower()
    email_verified = profile.get("email_verified")
    if not email or email_verified not in (True, "true"):
        return redirect("/login?error=google_auth_failed")

    name = profile.get("name") or email.split("@")[0]

    with db_module.session_scope() as db_session:
        user = db_session.query(models.User).filter_by(email=email).first()
        if user is None:
            # New account, no local password — it's Google-only until (if
            # ever) the user sets one.
            user = models.User(name=name, email=email, password_hash=None)
            db_session.add(user)
            db_session.flush()
        # Existing accounts (including password accounts sharing this
        # email) just log in as-is: Google has already verified the email,
        # so linking to the existing row is safe and avoids duplicates.
        user_id = user.id

    session["user_id"] = user_id
    return redirect("/dashboard")
