from __future__ import annotations

import logging

from mcp_server.config import get_settings
from mcp_server.db import get_session
from mcp_server.schemas.common import PaginationMeta, StandardResponse
from mcp_server.services.competitor_service import (
    CompetitorDataError,
    attach_nearby_competitors,
    get_competitor_index,
)
from mcp_server.services.media_service import MediaInventoryService
from mcp_server.services.request_validation import resolve_bounded_int, resolve_radius

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
    include_nearby_competitors: bool = False,
    competitor_radius_km: float | None = None,
    max_nearby_competitors: int | None = None,
    competitor_media_type: str = "",
    competitor_brand: str = "",
) -> str:
    """Search OOH media inventory (billboards, unipoles, gantries, bus shelters)

    by keyword, city, media type, owner, cost bounds, and audience metrics (reach, OTS).
    """
    settings = get_settings()
    try:
        competitor_index = None
        radius = settings.competitor_default_radius_km
        competitor_limit = settings.competitor_max_results
        if include_nearby_competitors:
            radius = resolve_radius(competitor_radius_km, settings.competitor_default_radius_km)
            competitor_limit = resolve_bounded_int(
                max_nearby_competitors,
                settings.competitor_max_results,
                minimum=1,
                maximum=50,
                name="max_nearby_competitors",
            )
            competitor_index = get_competitor_index()
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
            if competitor_index is not None:
                items = [
                    attach_nearby_competitors(
                        item,
                        competitor_index,
                        radius_km=radius,
                        limit=competitor_limit,
                        media_type=competitor_media_type,
                        brand=competitor_brand,
                        precision=settings.competitor_distance_precision,
                    )
                    for item in items
                ]
            response = StandardResponse.success_response(
                data=items,
                pagination=PaginationMeta(offset=offset, limit=limit, total=total),
            )
            return response.model_dump_json()
    except CompetitorDataError as exc:
        logger.exception("search_media_competitor_source_unavailable")
        return StandardResponse.error_response(
            code="COMPETITOR_DATA_UNAVAILABLE",
            message=str(exc),
        ).model_dump_json()
    except ValueError as exc:
        return StandardResponse.error_response(
            code="INVALID_ARGUMENT",
            message=str(exc),
        ).model_dump_json()
    except Exception as exc:
        logger.exception("search_media_failed")
        return StandardResponse.error_response(
            code="SEARCH_ERROR",
            message=f"Failed to search media inventory: {str(exc)}",
        ).model_dump_json()
