"""Shared API dependencies: admin auth (X-Admin-Token header) and the rate limiter."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..config import get_settings


def client_ip(request: Request) -> str:
    """Client IP behind the platform proxy. The proxy appends the real peer address LAST; earlier entries are
    client-supplied and could be forged to dodge the per-IP rate limit, so take the last one."""
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[-1].strip() if fwd else get_remote_address(request)


limiter = Limiter(key_func=client_ip, default_limits=[])


def is_admin_token(token: str | None) -> bool:
    expected = get_settings().admin_token
    return bool(expected and token and hmac.compare_digest(token.encode(), expected.encode()))


def admin_flag(x_admin_token: str | None = Header(default=None)) -> bool:
    return is_admin_token(x_admin_token)


def require_admin(x_admin_token: str | None = Header(default=None)) -> bool:
    if not get_settings().admin_token:
        raise HTTPException(503, "ADMIN_TOKEN is not configured on the server")
    if not is_admin_token(x_admin_token):
        raise HTTPException(401, "admin token required")
    return True
