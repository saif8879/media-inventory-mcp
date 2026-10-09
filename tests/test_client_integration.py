from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
import pytest

from mcp_server.server import create_mcp_server


@pytest.mark.asyncio
async def test_mcp_server_lists_all_tools():
    server = create_mcp_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    expected_tools = {
        "search_media",
        "get_media_details",
        "list_media",
        "get_media_statistics",
        "get_media_asset",
        "find_related_media",
    }
    assert expected_tools.issubset(tool_names)

    # Verify descriptions exist on all tools
    for tool in tools:
        if tool.name in expected_tools:
            assert tool.description is not None
            assert len(tool.description) > 10


@pytest.mark.asyncio
async def test_mcp_server_invokes_search_media():
    server = create_mcp_server()

    with patch("mcp_server.tools.search_media.MediaInventoryService") as mock_srv_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.search = AsyncMock(
            return_value=(
                [
                    {
                        "id": "e0a1b2c3-d4e5-6f7a-8b9c-0d1e2f3a4b5c",
                        "inventory_code": "MI1",
                        "city": "Mumbai",
                        "media_type": "BillBoard",
                        "total_cost": 50000.0,
                    }
                ],
                1,
            )
        )

        call_result = await server.call_tool(
            "search_media",
            {"query": "Mumbai", "limit": 5},
        )
        assert call_result is not None
        assert not call_result.is_error
        assert len(call_result.content) > 0

        parsed = json.loads(call_result.content[0].text)
        assert parsed["success"] is True
        assert len(parsed["data"]) == 1
        assert parsed["data"][0]["inventory_code"] == "MI1"
        assert parsed["pagination"]["total"] == 1


@pytest.mark.asyncio
async def test_mcp_server_invokes_get_media_details():
    server = create_mcp_server()

    with patch("mcp_server.tools.get_media_details.MediaInventoryService") as mock_srv_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.get_media_by_identifier = AsyncMock(
            return_value={
                "id": "e0a1b2c3-d4e5-6f7a-8b9c-0d1e2f3a4b5c",
                "inventory_code": "MI42",
                "city": "Delhi",
                "media_type": "Gantry",
                "admavin": {"reach": 250000, "ots": 800000},
            }
        )

        call_result = await server.call_tool(
            "get_media_details",
            {"identifier": "MI42"},
        )
        assert call_result is not None
        assert not call_result.is_error

        parsed = json.loads(call_result.content[0].text)
        assert parsed["success"] is True
        assert parsed["data"]["inventory_code"] == "MI42"
        assert parsed["data"]["city"] == "Delhi"


@pytest.mark.asyncio
async def test_mcp_server_invokes_get_media_statistics():
    server = create_mcp_server()

    with patch("mcp_server.tools.get_media_statistics.MediaInventoryService") as mock_srv_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.get_statistics = AsyncMock(
            return_value={
                "total_sites": 150,
                "total_cities": 8,
                "cost_metrics": {"avg_total_cost": 45000.0},
                "breakdown": {"Mumbai": 80, "Delhi": 70},
            }
        )

        call_result = await server.call_tool(
            "get_media_statistics",
            {"breakdown_by": "city"},
        )
        assert call_result is not None
        assert not call_result.is_error

        parsed = json.loads(call_result.content[0].text)
        assert parsed["success"] is True
        assert parsed["data"]["total_sites"] == 150
        assert parsed["data"]["breakdown"]["Mumbai"] == 80


@pytest.mark.asyncio
async def test_mcp_server_invokes_find_related_media():
    server = create_mcp_server()

    with patch("mcp_server.tools.find_related_media.MediaInventoryService") as mock_srv_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.find_related = AsyncMock(
            return_value=[
                {
                    "id": "1",
                    "inventory_code": "MI2",
                    "city": "Mumbai",
                    "distance_km": 1.25,
                    "relation_rationale": "Located 1.25 km away in Mumbai",
                }
            ]
        )

        call_result = await server.call_tool(
            "find_related_media",
            {"reference_identifier": "MI1", "radius_km": 5.0},
        )
        assert call_result is not None
        assert not call_result.is_error

        parsed = json.loads(call_result.content[0].text)
        assert parsed["success"] is True
        assert len(parsed["data"]) == 1
        assert parsed["data"][0]["distance_km"] == 1.25
