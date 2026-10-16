from __future__ import annotations

import json

import pytest
from mcp.server.mcpserver import MCPServer

from mcp_server.auth import MCPAuthMiddleware, PUBLIC_PATHS
from mcp_server.models import MediaInventory
from mcp_server.tools import register_tools
from mcp_server.tools.get_media_details import get_media_details_handler
from mcp_server.tools.search_media import search_media_handler


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


def test_health_auth_and_inventory_schema_stay_intact():
    assert "/health" in PUBLIC_PATHS
    assert "/" in PUBLIC_PATHS
    assert "/json/version" in PUBLIC_PATHS
    assert MCPAuthMiddleware.__name__ == "MCPAuthMiddleware"
    assert MediaInventory.__tablename__ == "media_inventory"
    assert hasattr(MediaInventory, "latitude")
    assert hasattr(MediaInventory, "longitude")
    assert hasattr(MediaInventory, "total_cost")


def test_competitor_tools_are_registered_without_removing_existing_tools():
    server = MCPServer(name="media-inventory-test", version="1.0.0")
    register_tools(server)
    names = {tool.name for tool in server._tool_manager.list_tools()}
    assert {
        "search_media",
        "get_media_details",
        "list_media",
        "get_media_statistics",
        "get_media_asset",
        "find_related_media",
        "generate_campaign_deck",
        "find_nearby_competitors",
        "generate_media_plan",
    } <= names
    search = server._tool_manager.get_tool("search_media")
    assert search is not None
    assert "include_nearby_competitors" in search.parameters["properties"]
    plan = server._tool_manager.get_tool("generate_media_plan")
    assert plan is not None
    assert "competitor" in plan.description.lower()


@pytest.mark.asyncio
async def test_search_media_preserves_filters_and_omits_competitors_by_default(monkeypatch):
    captured: dict = {}

    async def fake_search(self, **kwargs):
        captured.update(kwargs)
        return [{"inventory_code": "MI1", "city": "Mumbai", "latitude": 19.1, "longitude": 72.8}], 1

    monkeypatch.setattr("mcp_server.tools.search_media.get_session", lambda: FakeSession())
    monkeypatch.setattr("mcp_server.tools.search_media.MediaInventoryService.search", fake_search)

    raw = await search_media_handler(
        query="marine",
        city="Mumbai",
        media_type="BillBoard",
        limit=5,
        offset=2,
    )
    body = json.loads(raw)
    assert body["success"] is True
    assert body["error"] is None
    assert body["pagination"] == {"offset": 2, "limit": 5, "total": 1}
    assert body["data"][0]["inventory_code"] == "MI1"
    assert "nearby_competitors" not in body["data"][0]
    assert captured["query"] == "marine"
    assert captured["city"] == "Mumbai"
    assert captured["media_type"] == "BillBoard"
    assert captured.get("media_type_mode", "exact") == "exact"


@pytest.mark.asyncio
async def test_get_media_details_still_reports_missing_items(monkeypatch):
    async def fake_get(self, **kwargs):
        return None

    monkeypatch.setattr("mcp_server.tools.get_media_details.get_session", lambda: FakeSession())
    monkeypatch.setattr(
        "mcp_server.tools.get_media_details.MediaInventoryService.get_media_by_identifier",
        fake_get,
    )
    body = json.loads(await get_media_details_handler("MI404"))
    assert body["success"] is False
    assert body["error"]["code"] == "ITEM_NOT_FOUND"
