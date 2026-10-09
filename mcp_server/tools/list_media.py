from __future__ import annotations

import json
import logging
from typing import Any

from mcp_server.db import get_session
from mcp_server.schemas.common import PaginationMeta, StandardResponse
from mcp_server.services.media_service import MediaInventoryService

logger = logging.getLogger("mcp_server.tools.list_media")


async def list_media_handler(
    city: str = "",
    category: str = "",
    media_type: str = "",
    sub_type: str = "",
    orientation: str = "",
    media_owner: str = "",
    is_synced: bool | None = None,
    admavin_sync_status: str = "",
    offset: int = 0,
    limit: int = 20,
) -> str:
    """List and filter media inventory records with structured filters

    (city, category, media_type, sub_type/lighting, orientation, owner, sync status) with pagination.
    """
    try:
        async with get_session() as session:
            service = MediaInventoryService(session)
            items, total = await service.list_media(
                city=city or None,
                category=category or None,
                media_type=media_type or None,
                sub_type=sub_type or None,
                orientation=orientation or None,
                media_owner=media_owner or None,
                is_synced=is_synced,
                admavin_sync_status=admavin_sync_status or None,
                offset=offset,
                limit=limit,
            )
            return StandardResponse.success_response(
                data=items,
                pagination=PaginationMeta(offset=offset, limit=limit, total=total),
            ).model_dump_json()
    except Exception as exc:
        logger.exception("list_media_failed")
        return StandardResponse.error_response(
            code="LIST_ERROR",
            message=f"Failed to list media inventory: {str(exc)}",
        ).model_dump_json()
