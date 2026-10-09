from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
import pytest

from mcp_server.tools.search_media import search_media_handler
from mcp_server.tools.get_media_details import get_media_details_handler
from mcp_server.tools.list_media import list_media_handler
from mcp_server.tools.get_media_statistics import get_media_statistics_handler
from mcp_server.tools.get_media_asset import get_media_asset_handler
from mcp_server.tools.find_related_media import find_related_media_handler


@pytest.mark.asyncio
async def test_search_media_handler():
    with patch("mcp_server.tools.search_media.MediaInventoryService") as mock_srv_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.search = AsyncMock(return_value=([{"id": "1", "inventory_code": "MI1"}], 1))

        res_str = await search_media_handler(query="billboard", limit=10)
        data = json.loads(res_str)

        assert data["success"] is True
        assert len(data["data"]) == 1
        assert data["pagination"]["total"] == 1
        assert data["error"] is None


@pytest.mark.asyncio
async def test_get_media_details_handler_not_found():
    with patch("mcp_server.tools.get_media_details.MediaInventoryService") as mock_srv_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.get_media_by_identifier = AsyncMock(return_value=None)

        res_str = await get_media_details_handler(identifier="MI999")
        data = json.loads(res_str)

        assert data["success"] is False
        assert data["data"] is None
        assert data["error"]["code"] == "ITEM_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_media_asset_handler():
    with patch("mcp_server.tools.get_media_asset.MediaInventoryService") as mock_srv_cls, \
         patch("mcp_server.tools.get_media_asset.S3AssetService") as mock_s3_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.get_media_by_identifier = AsyncMock(return_value={
            "id": "123",
            "inventory_code": "MI1",
            "image_url": "media-inventory/MI1/photo.jpg",
        })

        mock_s3 = mock_s3_cls.return_value
        mock_s3.get_asset_info.return_value = {
            "key": "media-inventory/MI1/photo.jpg",
            "url": "https://s3.amazonaws.com/presigned",
            "is_presigned": True,
            "format": "jpg",
            "expires_in_seconds": 900,
        }

        res_str = await get_media_asset_handler(identifier="MI1")
        data = json.loads(res_str)

        assert data["success"] is True
        assert data["data"]["url"] == "https://s3.amazonaws.com/presigned"
        assert data["data"]["format"] == "jpg"
