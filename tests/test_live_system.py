from __future__ import annotations

import json
import pytest
from httpx import ASGITransport, AsyncClient

from mcp_server.server import create_app, create_mcp_server


@pytest.mark.asyncio
async def test_live_system_verification():
    """Verify live connectivity and functionality against production database and S3."""
    # 1. Verify FastAPI HTTP endpoints
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8090"
    ) as client:
        # Public health check
        health_res = await client.get("/health")
        assert health_res.status_code == 200
        health_data = health_res.json()
        assert health_data["status"] == "ok"
        assert health_data["service"] == "media-inventory-mcp"
        assert len(health_data["tools"]) == 6

        # Unauthorized access protection
        unauth_res = await client.get("/sse")
        assert unauth_res.status_code == 401
        assert "Unauthorized" in unauth_res.json().get("detail", "")

    # 2. Verify MCP Server and tool execution
    server = create_mcp_server()

    # Tool 1: search_media
    res_search = await server.call_tool("search_media", {"query": "bandra", "limit": 2})
    assert not res_search.is_error
    data_search = json.loads(res_search.content[0].text)
    assert data_search["success"] is True
    items = data_search.get("data", [])
    assert len(items) > 0
    sample_code = items[0]["inventory_code"]
    assert sample_code is not None

    # Tool 2: get_media_details
    res_details = await server.call_tool("get_media_details", {"identifier": sample_code})
    assert not res_details.is_error
    data_details = json.loads(res_details.content[0].text)
    assert data_details["success"] is True
    detail = data_details["data"]
    assert detail["inventory_code"] == sample_code
    assert "location" in detail
    assert "total_cost" in detail

    # Tool 3: get_media_statistics
    res_stats = await server.call_tool(
        "get_media_statistics", {"city": "mumbai", "breakdown_by": "media_type"}
    )
    assert not res_stats.is_error
    data_stats = json.loads(res_stats.content[0].text)
    assert data_stats["success"] is True
    stats = data_stats["data"]
    assert stats["total_sites"] > 0
    assert "cost_metrics" in stats
    assert "breakdown" in stats

    # Tool 4: list_media
    res_list = await server.call_tool("list_media", {"city": "mumbai", "limit": 3})
    assert not res_list.is_error
    data_list = json.loads(res_list.content[0].text)
    assert data_list["success"] is True
    assert len(data_list.get("data", [])) > 0

    # Tool 5: find_related_media
    res_related = await server.call_tool(
        "find_related_media", {"reference_identifier": sample_code, "radius_km": 5.0, "limit": 2}
    )
    assert not res_related.is_error
    data_related = json.loads(res_related.content[0].text)
    assert data_related["success"] is True

    # Tool 6: get_media_asset
    res_asset = await server.call_tool("get_media_asset", {"identifier": sample_code})
    assert not res_asset.is_error
    data_asset = json.loads(res_asset.content[0].text)
    assert data_asset["success"] is True
    asset = data_asset["data"]
    assert "url" in asset
    assert asset["url"].startswith("http")
    assert asset["is_presigned"] is True
