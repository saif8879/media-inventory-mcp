from __future__ import annotations

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server.config import get_settings

logger = logging.getLogger("mcp_server.auth")

PUBLIC_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/favicon.ico"})


class MCPAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Allow open access to monitoring and documentation endpoints
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        settings = get_settings()
        # If no key configured (e.g. open local development), permit request
        if not settings.mcp_api_key:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-MCP-Key", "")
        token_query = request.query_params.get("token", "")

        extracted_token = ""
        if auth_header.startswith("Bearer "):
            extracted_token = auth_header[7:].strip()
        elif api_key_header:
            extracted_token = api_key_header.strip()
        elif token_query:
            extracted_token = token_query.strip()

        if not extracted_token or extracted_token != settings.mcp_api_key:
            logger.warning(
                "unauthorized_mcp_access_attempt",
                extra={"path": request.url.path, "has_auth_header": bool(auth_header)},
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized: Invalid or missing MCP API key"},
            )

        return await call_next(request)
