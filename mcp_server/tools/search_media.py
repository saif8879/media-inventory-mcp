from __future__ import annotations

import json
import logging
from typing import Any

from mcp_server.db import get_session
from mcp_server.schemas.common import PaginationMeta, StandardResponse
from mcp_server.services.media_service import MediaInventoryService

logger = logging.getLogger("mcp_server.tools.search_media")


async def search_media_handler(
    query: str = "",
    city: str = "",
    media_type: str = "",
    media_owner: str = "",
    min_total_cost: float | None = None,
    max_total_cost: float | None = None,
    min_reach: int | None = None,
    min_ots: int | None = None,
    has_image: bool | None = None,
    offset: int = 0,
    limit: int = 20,
) -> str:
    """Search OOH media inventory (billboards, unipoles, gantries, bus shelters)

    by keyword, city, media type, owner, cost bounds, and audience metrics (reach, OTS).
    """
    try:
        async with get_session() as session:
            service = MediaInventoryService(session)
            items, total = await service.search(
                query=query or None,
                city=city or None,
                media_type=media_type or None,
                media_owner=media_owner or None,
                min_total_cost=min_total_cost,
                max_total_cost=max_total_cost,
                min_reach=min_reach,
                min_ots=min_ots,
                has_image=has_image,
                offset=offset,
                limit=limit,
            )
            response = StandardResponse.success_response(
                data=items,
                pagination=PaginationMeta(offset=offset, limit=limit, total=total),
            )
            return response.model_dump_json()
    except Exception as exc:
        logger.exception("search_media_failed")
        return StandardResponse.error_response(
            code="SEARCH_ERROR",
            message=f"Failed to search media inventory: {str(exc)}",
        ).model_dump_json()
