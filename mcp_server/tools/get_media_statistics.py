from __future__ import annotations

import json
import logging
from typing import Any

from mcp_server.db import get_session
from mcp_server.schemas.common import StandardResponse
from mcp_server.services.media_service import MediaInventoryService

logger = logging.getLogger("mcp_server.tools.get_media_statistics")


async def get_media_statistics_handler(
    city: str = "",
    media_type: str = "",
    breakdown_by: str = "",
) -> str:
    """Get aggregated media inventory analytics: total sites, cities, media types,

    cost metrics (avg, min, max), audience reach totals, and optional categorical breakdowns
    by 'city', 'media_type', 'category', or 'media_owner'.
    """
    valid_breakdowns = {"", "city", "media_type", "category", "media_owner"}
    clean_bd = breakdown_by.strip().lower()
    if clean_bd and clean_bd not in valid_breakdowns:
        return StandardResponse.error_response(
            code="INVALID_ARGUMENT",
            message=f"Invalid breakdown_by '{breakdown_by}'. Must be one of: 'city', 'media_type', 'category', 'media_owner'",
        ).model_dump_json()

    try:
        async with get_session() as session:
            service = MediaInventoryService(session)
            stats = await service.get_statistics(
                city=city or None,
                media_type=media_type or None,
                breakdown_by=clean_bd or None,
            )
            return StandardResponse.success_response(data=stats).model_dump_json()
    except Exception as exc:
        logger.exception("get_media_statistics_failed")
        return StandardResponse.error_response(
            code="STATS_ERROR",
            message=f"Failed to calculate media statistics: {str(exc)}",
        ).model_dump_json()
