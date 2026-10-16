from __future__ import annotations

import logging

from mcp_server.config import get_settings
from mcp_server.db import get_session
from mcp_server.schemas.common import StandardResponse
from mcp_server.services.competitor_service import (
    CompetitorDataError,
    attach_nearby_competitors,
    get_competitor_index,
)
from mcp_server.services.media_service import MediaInventoryService
from mcp_server.services.request_validation import resolve_bounded_int, resolve_radius

logger = logging.getLogger("mcp_server.tools.find_nearby_competitors")


async def find_nearby_competitors_handler(
    identifier: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    limit: int | None = None,
    media_type: str = "",
    brand: str = "",
) -> str:
    """Find competitor media near an inventory site or a latitude/longitude pair."""
    settings = get_settings()
    try:
        radius = resolve_radius(radius_km, settings.competitor_default_radius_km)
        result_limit = resolve_bounded_int(
            limit,
            settings.competitor_max_results,
            minimum=1,
            maximum=50,
            name="limit",
        )
    except ValueError as exc:
        return _invalid(str(exc))

    clean_identifier = identifier.strip()
    if not clean_identifier and (latitude is None or longitude is None):
        return _invalid(
            "Either identifier (inventory code or UUID) or both latitude and longitude must be provided"
        )

    if clean_identifier:
        return await _from_inventory(
            clean_identifier,
            radius=radius,
            result_limit=result_limit,
            media_type=media_type,
            brand=brand,
            precision=settings.competitor_distance_precision,
        )

    return _from_coordinates(
        latitude,
        longitude,
        radius=radius,
        result_limit=result_limit,
        media_type=media_type,
        brand=brand,
        precision=settings.competitor_distance_precision,
    )


async def _from_inventory(
    identifier: str,
    *,
    radius: float,
    result_limit: int,
    media_type: str,
    brand: str,
    precision: int,
) -> str:
    try:
        async with get_session() as session:
            item = await MediaInventoryService(session).get_media_by_identifier(
                identifier=identifier,
                include_price_history=False,
                include_audience_metrics=True,
            )
    except Exception as exc:
        logger.exception("find_nearby_competitors_inventory_failed")
        return StandardResponse.error_response(
            code="RETRIEVAL_ERROR",
            message=f"Failed to retrieve media inventory: {exc}",
        ).model_dump_json()

    if not item:
        return StandardResponse.error_response(
            code="ITEM_NOT_FOUND",
            message=f"Media inventory site with identifier '{identifier}' was not found",
            details={"identifier": identifier},
        ).model_dump_json()

    if item.get("latitude") is None or item.get("longitude") is None:
        enriched = attach_nearby_competitors(
            item,
            _empty_index(),
            radius_km=radius,
            limit=result_limit,
            media_type=media_type,
            brand=brand,
            precision=precision,
        )
        return _success(item, enriched["competitor_search"], [])

    try:
        index = get_competitor_index()
        enriched = attach_nearby_competitors(
            item,
            index,
            radius_km=radius,
            limit=result_limit,
            media_type=media_type,
            brand=brand,
            precision=precision,
        )
    except CompetitorDataError as exc:
        logger.exception("find_nearby_competitors_source_unavailable")
        return _source_error(exc)
    except Exception as exc:
        logger.exception("find_nearby_competitors_failed")
        return StandardResponse.error_response(
            code="COMPETITOR_SEARCH_ERROR",
            message=f"Failed to find nearby competitors: {exc}",
        ).model_dump_json()

    return _success(item, enriched["competitor_search"], enriched["nearby_competitors"])


def _from_coordinates(
    latitude: float | None,
    longitude: float | None,
    *,
    radius: float,
    result_limit: int,
    media_type: str,
    brand: str,
    precision: int,
) -> str:
    try:
        index = get_competitor_index()
        result = index.find_nearby(
            latitude,
            longitude,
            radius_km=radius,
            limit=result_limit,
            media_type=media_type or None,
            brand=brand or None,
            precision=precision,
        )
    except CompetitorDataError as exc:
        logger.exception("find_nearby_competitors_source_unavailable")
        return _source_error(exc)
    except ValueError as exc:
        return _invalid(str(exc))
    except Exception as exc:
        logger.exception("find_nearby_competitors_failed")
        return StandardResponse.error_response(
            code="COMPETITOR_SEARCH_ERROR",
            message=f"Failed to find nearby competitors: {exc}",
        ).model_dump_json()

    search = {
        "status": result["status"],
        "radius_km": result["radius_km"],
        "catalog_size": result["catalog_size"],
        "message": result["message"],
    }
    return StandardResponse.success_response(
        data={
            "inventory": None,
            "latitude": latitude,
            "longitude": longitude,
            "radius_km": radius,
            "competitor_search": search,
            "nearby_competitors": result["competitors"],
        }
    ).model_dump_json()


def _success(item: dict, search: dict, competitors: list) -> str:
    return StandardResponse.success_response(
        data={
            "inventory": item,
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
            "radius_km": search.get("radius_km"),
            "competitor_search": search,
            "nearby_competitors": competitors,
        }
    ).model_dump_json()


def _empty_index():
    from mcp_server.services.competitor_service import CompetitorIndex

    return CompetitorIndex([], skipped_invalid=0)


def _invalid(message: str) -> str:
    return StandardResponse.error_response(code="INVALID_ARGUMENT", message=message).model_dump_json()


def _source_error(exc: CompetitorDataError) -> str:
    return StandardResponse.error_response(
        code="COMPETITOR_DATA_UNAVAILABLE",
        message=str(exc),
    ).model_dump_json()
