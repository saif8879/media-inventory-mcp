from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.mcpserver import MCPServer
from sqlalchemy.ext.asyncio import async_sessionmaker

from mcp_server.auth import MCPAuthMiddleware
from mcp_server.config import get_settings
from mcp_server.db import engine
from mcp_server.oauth.google import GoogleOAuth
from mcp_server.oauth.routes import GoogleLogin, register_oauth_routes
from mcp_server.oauth.store import SqlOAuthStore
from mcp_server.tools import register_tools

logger = logging.getLogger("mcp_server")


def create_mcp_server() -> MCPServer:
    """Create and configure the MCPServer instance with all tools registered."""
    server = MCPServer(name="media-inventory", version="1.0.0")
    register_tools(server)
    return server


def create_app(
    *,
    oauth_database_url: str | None = None,
    google: GoogleLogin | None = None,
) -> FastAPI:
    """Create the FastAPI application hosting the MCP server and HTTP transports."""
    settings = get_settings()
    server = create_mcp_server()
    oauth_store = SqlOAuthStore()
    google_login = google if google is not None else _google_login(settings)
    # Pass the real bind host. The SDK otherwise assumes 127.0.0.1 and rejects
    # the public Host header with 421.
    streamable_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        host=settings.mcp_server_host,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "media_inventory_mcp_server_starting",
            extra={"port": settings.mcp_server_port, "host": settings.mcp_server_host},
        )
        oauth_engine, owns_engine = _oauth_engine(oauth_database_url)
        oauth_store.bind(async_sessionmaker(oauth_engine, expire_on_commit=False))
        await oauth_store.setup(oauth_engine)
        async with server.session_manager.run():
            yield
        if owns_engine:
            await oauth_engine.dispose()
        logger.info("media_inventory_mcp_server_stopped")

    app = FastAPI(
        title="Media Inventory MCP Server",
        description="Production-grade Model Context Protocol server exposing OOH Media Inventory data to AI assistants.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Authentication middleware
    app.add_middleware(MCPAuthMiddleware)
    register_oauth_routes(app, settings, oauth_store, google_login)

    # Health check endpoint. "/" and "/json/version" are public so a browser
    # probe does not come back as an unauthorized MCP call.
    @app.get("/")
    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "media-inventory-mcp",
            "version": "1.0.0",
            "tools": [
                "search_media",
                "get_media_details",
                "list_media",
                "get_media_statistics",
                "get_media_asset",
                "find_related_media",
                "generate_campaign_deck",
                "find_nearby_competitors",
                "generate_media_plan",
            ],
        }

    @app.get("/json/version")
    async def browser_probe():
        return {"status": "ok", "service": "media-inventory-mcp"}

    # SSE stays available for older clients. Streamable HTTP on /mcp is what
    # Claude custom connectors call with POST.
    sse_starlette_app = server.sse_app(host=settings.mcp_server_host)
    for route in sse_starlette_app.routes:
        app.router.routes.append(route)
    for route in streamable_app.routes:
        app.router.routes.append(route)

    return app


def _google_login(settings):
    if not (
        settings.mcp_public_url.strip()
        and settings.google_client_id.strip()
        and settings.google_client_secret.strip()
    ):
        return None
    return GoogleOAuth(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=f"{settings.mcp_public_url.rstrip('/')}/auth/google/callback",
        hosted_domain=settings.google_hosted_domain,
    )


def _oauth_engine(oauth_database_url: str | None):
    if not oauth_database_url:
        return engine, False
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.ext.asyncio import create_async_engine

    kwargs = {}
    if oauth_database_url.startswith("sqlite"):
        kwargs["poolclass"] = StaticPool
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(oauth_database_url, **kwargs), True


app = create_app()


def main():
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "mcp_server.server:app",
        host=settings.mcp_server_host,
        port=settings.mcp_server_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
