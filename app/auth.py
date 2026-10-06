"""Invite-only magic-link sign-in and signed session cookies."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import Settings
from app.db import Database

SESSION_COOKIE = "cw_session"
SESSION_MAX_AGE = 30 * 24 * 3600
LOGIN_MAX_AGE = 15 * 60
LOGIN_RATE_LIMIT = 3  # links per email per LOGIN_MAX_AGE


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _serializer(settings: Settings, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=salt)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_allowed(db: Database, settings: Settings, email: str) -> bool:
    if settings.admin_email and email == normalize_email(settings.admin_email):
        return True
    with db.connect() as conn:
        return bool(
            conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
            or conn.execute("SELECT 1 FROM invites WHERE email = ?", (email,)).fetchone()
        )


def create_login_token(db: Database, settings: Settings, email: str) -> str | None:
    """Return a single-use token, or None when this email hit the rate limit."""
    since = (datetime.now(UTC) - timedelta(seconds=LOGIN_MAX_AGE)).isoformat()
    jti = uuid.uuid4().hex
    with db.connect() as conn:
        (recent,) = conn.execute(
            "SELECT COUNT(*) FROM login_tokens WHERE email = ? AND created_at > ?", (email, since)
        ).fetchone()
        if recent >= LOGIN_RATE_LIMIT:
            return None
        conn.execute(
            "INSERT INTO login_tokens (jti, email, created_at) VALUES (?, ?, ?)",
            (jti, email, utcnow()),
        )
    return _serializer(settings, "login").dumps({"e": email, "j": jti})


def peek_login_token(settings: Settings, token: str) -> str | None:
    try:
        return _serializer(settings, "login").loads(token, max_age=LOGIN_MAX_AGE)["e"]
    except (BadSignature, SignatureExpired, KeyError, TypeError):
        return None


def consume_login_token(db: Database, settings: Settings, token: str) -> int | None:
    """Validate a login token, mark it used and return the (possibly new) user's id."""
    try:
        data = _serializer(settings, "login").loads(token, max_age=LOGIN_MAX_AGE)
        email, jti = data["e"], data["j"]
    except (BadSignature, SignatureExpired, KeyError, TypeError):
        return None
    if not is_allowed(db, settings, email):
        return None
    is_admin = int(bool(settings.admin_email) and email == normalize_email(settings.admin_email))
    with db.connect() as conn:
        updated = conn.execute(
            "UPDATE login_tokens SET used_at = ? WHERE jti = ? AND used_at IS NULL",
            (utcnow(), jti),
        ).rowcount
        if not updated:
            return None
        conn.execute(
            "INSERT INTO users (email, is_admin, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(email) DO UPDATE SET is_admin = MAX(is_admin, excluded.is_admin)",
            (email, is_admin, utcnow()),
        )
        (user_id,) = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    return user_id


def session_cookie_value(settings: Settings, user_id: int) -> str:
    return _serializer(settings, "session").dumps(user_id)


def pause_token(settings: Settings, user_id: int) -> str:
    return _serializer(settings, "pause").dumps(user_id)


def read_pause_token(settings: Settings, token: str) -> int | None:
    try:
        return _serializer(settings, "pause").loads(token, max_age=90 * 24 * 3600)
    except (BadSignature, SignatureExpired):
        return None


def current_user(request: Request):
    settings: Settings = request.app.state.settings
    db: Database = request.app.state.db
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        user_id = _serializer(settings, "session").loads(raw, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    with db.connect() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def require_user(request: Request):
    user = current_user(request)
    if user is None:
        login = request.app.state.settings.path("/login")
        raise HTTPException(status_code=303, headers={"Location": login})
    return user


def require_admin(request: Request):
    user = require_user(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admins only")
    return user
