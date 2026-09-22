"""Admin authentication: single admin account, signed session cookie.

Cookie flags: HttpOnly + SameSite=Lax; Secure is added whenever the
configured public base URL is HTTPS.
"""

from __future__ import annotations

import logging

import bcrypt
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeSerializer

from .config import ConfigManager

logger = logging.getLogger("subrelay.auth")

SESSION_COOKIE = "sr_session"


def _serializer(cfg: ConfigManager) -> URLSafeSerializer:
    return URLSafeSerializer(cfg.config.server.session_secret, salt="subrelay-session")


def _is_secure_context(cfg: ConfigManager) -> bool:
    return cfg.config.server.public_base_url.lower().startswith("https://")


def verify_password(cfg: ConfigManager, username: str, password: str) -> bool:
    server = cfg.config.server
    if not username or not password:
        return False
    if username != server.admin_username:
        return False
    stored = server.admin_password_hash
    if not stored:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("ascii"))
    except ValueError:
        return False


def login(response, cfg: ConfigManager, username: str) -> None:
    token = _serializer(cfg).dumps({"u": username})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=cfg.config.server.session_max_age,
        httponly=True,
        samesite="lax",
        secure=_is_secure_context(cfg),
        path="/",
    )


def logout(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_admin(request: Request) -> str | None:
    cfg: ConfigManager = request.app.state.cfg
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = _serializer(cfg).loads(token, max_age=cfg.config.server.session_max_age)
    except BadSignature:
        return None
    username = data.get("u")
    return username if username == cfg.config.server.admin_username else None


def require_admin(request: Request) -> str:
    """API dependency: 401 when not logged in."""
    username = current_admin(request)
    if username is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return username
