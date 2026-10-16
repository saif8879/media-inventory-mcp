from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server.config import Settings, get_settings
from mcp_server.oauth.routes import resource_audiences
from mcp_server.oauth.tokens import TokenRejected, decode_access_token

logger = logging.getLogger("mcp_server.auth")

PUBLIC_PATHS = frozenset(
    {
        "/",
        "/health",
        "/json/version",
        "/docs",
        "/openapi.json",
        "/favicon.ico",
        "/register",
        "/authorize",
        "/token",
        "/auth/google/callback",
    }
)


def oauth_is_configured(settings: Settings) -> bool:
    return bool(
        settings.mcp_public_url.strip()
        and settings.google_client_id.strip()
        and settings.google_client_secret.strip()
        and settings.oauth_jwt_secret.strip()
        and settings.google_hosted_domain.strip()
    )


class MCPAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/.well-known/oauth-"):
            return await call_next(request)

        settings = get_settings()
        if not oauth_is_configured(settings):
            return JSONResponse(
                status_code=503,
                content={"detail": "Google OAuth is not configured"},
            )

        token = _bearer_token(request.headers.get("Authorization", ""))
        if not token:
            return _unauthorized(settings, "Missing access token")

        public = settings.mcp_public_url.rstrip("/")
        try:
            claims = decode_access_token(
                token,
                secret=settings.oauth_jwt_secret,
                issuer=public,
                audiences=resource_audiences(public),
            )
        except TokenRejected:
            logger.warning(
                "unauthorized_mcp_access_attempt",
                extra={"path": request.url.path},
            )
            return _unauthorized(settings, "Invalid or expired access token")

        hosted = str(claims.get("hd") or "").lower()
        if hosted != settings.google_hosted_domain.strip().lower():
            return _unauthorized(settings, "Account is outside the wrap2earn organization")

        request.state.oauth_email = claims.get("email", "")
        return await call_next(request)


def _bearer_token(header: str) -> str:
    if not header.startswith("Bearer "):
        return ""
    return header[7:].strip()


def _unauthorized(settings: Settings, description: str) -> JSONResponse:
    metadata = f"{settings.mcp_public_url.rstrip('/')}/.well-known/oauth-protected-resource"
    return JSONResponse(
        status_code=401,
        content={"detail": f"Unauthorized: {description}"},
        headers={
            "WWW-Authenticate": f'Bearer error="invalid_token", error_description="{description}", resource_metadata="{metadata}"'
        },
    )
