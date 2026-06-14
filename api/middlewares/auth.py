# -*- coding: utf-8 -*-
"""
Auth middleware: protect API routes and SPA routes when admin auth is enabled.
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.auth import COOKIE_NAME, is_auth_enabled, verify_session

logger = logging.getLogger(__name__)

# Paths that are always accessible without authentication.
EXEMPT_PATHS = frozenset({
    "/api/v1/auth/login",
    "/api/v1/auth/status",
    "/api/health",
    "/api/v1/health",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/login",
    "/ping",
})

# Static asset path prefixes that must be accessible without auth
# so the login page can render.
STATIC_ASSET_PREFIXES = ("/assets/", "/stocks.index.json")


def _path_exempt(path: str) -> bool:
    """Check if path is exempt from auth."""
    normalized = path.rstrip("/") or "/"
    if normalized in EXEMPT_PATHS:
        return True
    for prefix in STATIC_ASSET_PREFIXES:
        if normalized.startswith(prefix):
            return True
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    """Require valid session for all routes when auth is enabled.

    Protects both /api/v1/* and SPA routes (/, /settings, etc.).
    Static assets (/assets/*) and auth endpoints are exempt.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ):
        if not is_auth_enabled():
            return await call_next(request)

        path = request.url.path
        if _path_exempt(path):
            return await call_next(request)

        cookie_val = request.cookies.get(COOKIE_NAME)
        if not cookie_val or not verify_session(cookie_val):
            # For API routes, return JSON 401
            if path.startswith("/api/"):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "unauthorized",
                        "message": "Login required",
                    },
                )
            # For SPA routes, redirect to login page
            return RedirectResponse(
                url="/login",
                status_code=302,
            )

        return await call_next(request)


def add_auth_middleware(app):
    """Add auth middleware to protect API and SPA routes.

    The middleware is always registered; whether auth is enforced is determined
    at request time by is_auth_enabled() so the decision stays consistent across
    any runtime configuration reload.
    """
    app.add_middleware(AuthMiddleware)
