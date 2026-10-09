from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.mcpserver import MCPServer

from mcp_server.auth import MCPAuthMiddleware
from mcp_server.config import get_settings
from mcp_server.tools import register_tools

logger = logging.getLogger("mcp_server")


def create_mcp_server() -> MCPServer:
    """Create and configure the MCPServer instance with all tools registered."""
    server = MCPServer(name="media-inventory", version="1.0.0")
    register_tools(server)
    return server


def create_app() -> FastAPI:
    """Create the FastAPI application hosting the MCP server and HTTP transports."""
    settings = get_settings()
    server = create_mcp_server()
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
        async with server.session_manager.run():
            yield
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

    # Health check endpoint
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
            ],
        }

    # SSE stays available for older clients. Streamable HTTP on /mcp is what
    # Claude custom connectors call with POST.
    sse_starlette_app = server.sse_app(host=settings.mcp_server_host)
    for route in sse_starlette_app.routes:
        app.router.routes.append(route)
    for route in streamable_app.routes:
        app.router.routes.append(route)

    return app


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
