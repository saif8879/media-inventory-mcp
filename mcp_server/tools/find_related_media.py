from __future__ import annotations

import json
import logging
from typing import Any

from mcp_server.db import get_session
from mcp_server.schemas.common import PaginationMeta, StandardResponse
from mcp_server.services.media_service import MediaInventoryService

logger = logging.getLogger("mcp_server.tools.find_related_media")


async def find_related_media_handler(
    reference_identifier: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 5.0,
    same_media_type: bool = False,
    limit: int = 10,
) -> str:
    """Find geographically nearby media inventory sites given a reference site

    inventory code or GPS coordinates (latitude, longitude), within a radius in kilometers.
    """
    if not reference_identifier and (latitude is None or longitude is None):
        return StandardResponse.error_response(
            code="INVALID_ARGUMENT",
            message="Either reference_identifier (e.g. 'MI1') or both latitude and longitude must be provided",
        ).model_dump_json()

    try:
        async with get_session() as session:
            service = MediaInventoryService(session)
            items = await service.find_related(
                reference_identifier=reference_identifier or None,
                latitude=latitude,
                longitude=longitude,
                radius_km=radius_km,
                same_media_type=same_media_type,
                limit=limit,
            )
            return StandardResponse.success_response(
                data=items,
                pagination=PaginationMeta(offset=0, limit=limit, total=len(items)),
            ).model_dump_json()
    except Exception as exc:
        logger.exception("find_related_media_failed")
        return StandardResponse.error_response(
            code="DISCOVERY_ERROR",
            message=f"Failed to find related media: {str(exc)}",
        ).model_dump_json()
