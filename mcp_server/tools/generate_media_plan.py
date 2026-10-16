from __future__ import annotations

import logging

from mcp_server.config import get_settings
from mcp_server.db import get_session
from mcp_server.schemas.common import StandardResponse
from mcp_server.services.competitor_service import CompetitorDataError, get_competitor_index
from mcp_server.services.geo import is_billboard_family
from mcp_server.services.media_plan_service import MediaPlanService
from mcp_server.services.media_service import MediaInventoryService
from mcp_server.services.request_validation import (
    resolve_bounded_int,
    resolve_budget,
    resolve_radius,
)

logger = logging.getLogger("mcp_server.tools.generate_media_plan")


async def generate_media_plan_handler(
    brand: str,
    city: str,
    budget: float,
    media_type: str = "",
    objective: str = "",
    query: str = "",
    radius_km: float | None = None,
    max_competitors: int | None = None,
    competitor_media_type: str = "",
    competitor_brand: str = "",
    max_sites: int | None = None,
) -> str:
    """Build a budget-aware inventory plan and attach nearby competitor media to every site."""
    settings = get_settings()
    clean_brand = brand.strip()
    clean_city = city.strip()
    if not clean_brand or not clean_city:
        return _invalid("brand and city are required")
    try:
        amount = resolve_budget(budget)
        radius = resolve_radius(radius_km, settings.competitor_default_radius_km)
        resolved_competitor_type = _competitor_type(competitor_media_type, media_type)
        default_competitor_limit = settings.competitor_max_results
        if not resolved_competitor_type:
            default_competitor_limit = 50
        competitor_limit = resolve_bounded_int(
            max_competitors,
            default_competitor_limit,
            minimum=1,
            maximum=50,
            name="max_competitors",
        )
        site_limit = resolve_bounded_int(
            max_sites,
            settings.media_plan_max_sites,
            minimum=1,
            maximum=25,
            name="max_sites",
        )
    except ValueError as exc:
        return _invalid(str(exc))

    try:
        index = get_competitor_index()
        async with get_session() as session:
            plan = await MediaPlanService(MediaInventoryService(session), index).generate(
                brand=clean_brand,
                city=clean_city,
                budget=amount,
                media_type=media_type.strip(),
                objective=objective.strip(),
                query=query.strip(),
                radius_km=radius,
                max_competitors=competitor_limit,
                max_candidates=settings.media_plan_max_candidates,
                max_sites=site_limit,
                competitor_media_type=resolved_competitor_type,
                competitor_brand=competitor_brand.strip(),
                precision=settings.competitor_distance_precision,
            )
    except CompetitorDataError as exc:
        logger.exception("generate_media_plan_competitor_source_unavailable")
        return StandardResponse.error_response(
            code="COMPETITOR_DATA_UNAVAILABLE",
            message=str(exc),
        ).model_dump_json()
    except ValueError as exc:
        return _invalid(str(exc))
    except Exception as exc:
        logger.exception("generate_media_plan_failed")
        return StandardResponse.error_response(
            code="MEDIA_PLAN_ERROR",
            message=f"Failed to generate media plan: {exc}",
        ).model_dump_json()

    return StandardResponse.success_response(data=plan).model_dump_json()


def _competitor_type(competitor_media_type: str, campaign_media_type: str) -> str:
    """Competitor type filter. Empty means every type inside the radius.

    A billboard brief keeps the inventory search on billboards. Nearby competitor
    rows are then every placement within the radius, matched by latitude and
    longitude. A different competitor type, such as bus shelter, still filters.
    """
    requested = competitor_media_type.strip()
    campaign = campaign_media_type.strip()
    if requested.casefold() == "any":
        return ""
    if is_billboard_family(campaign):
        if requested and not is_billboard_family(requested):
            return requested
        return ""
    if requested:
        return requested
    return campaign


def _invalid(message: str) -> str:
    return StandardResponse.error_response(code="INVALID_ARGUMENT", message=message).model_dump_json()
