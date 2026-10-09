from __future__ import annotations

import argparse
import sys

from mcp_server.server import create_mcp_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Media Inventory MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport to run: stdio (for Cursor, Claude Desktop) or sse (HTTP server)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        server = create_mcp_server()
        server.run(transport="stdio")
    else:
        import uvicorn
        from mcp_server.config import get_settings

        settings = get_settings()
        uvicorn.run(
            "mcp_server.server:app",
            host=settings.mcp_server_host,
            port=settings.mcp_server_port,
            reload=False,
        )


if __name__ == "__main__":
    main()
