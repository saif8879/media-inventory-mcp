from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_server.tools.find_related_media import find_related_media_handler
from mcp_server.tools.get_media_asset import get_media_asset_handler
from mcp_server.tools.get_media_details import get_media_details_handler
from mcp_server.tools.get_media_statistics import get_media_statistics_handler
from mcp_server.tools.list_media import list_media_handler
from mcp_server.tools.search_media import search_media_handler

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


def register_tools(server: MCPServer) -> None:
    """Register all media inventory tools onto the MCPServer instance."""

    @server.tool(
        name="search_media",
        description=(
            "Search OOH media inventory (billboards, unipoles, gantries, bus shelters) "
            "by keyword query, city, media type, concessionaire/owner, cost bounds, "
            "and audience metrics (reach, OTS). Returns paginated summary records."
        ),
    )
    async def search_media(
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
        return await search_media_handler(
            query=query,
            city=city,
            media_type=media_type,
            media_owner=media_owner,
            min_total_cost=min_total_cost,
            max_total_cost=max_total_cost,
            min_reach=min_reach,
            min_ots=min_ots,
            has_image=has_image,
            offset=offset,
            limit=limit,
        )

    @server.tool(
        name="get_media_details",
        description=(
            "Retrieve complete details for a single media inventory site by its unique "
            "inventory code (e.g. 'MI1', 'MI42') or UUID id. Includes dimensions, orientation, "
            "costs, recent quotation price negotiations, and AdMavin audience demographics."
        ),
    )
    async def get_media_details(
        identifier: str,
        include_price_history: bool = True,
        include_audience_metrics: bool = True,
    ) -> str:
        return await get_media_details_handler(
            identifier=identifier,
            include_price_history=include_price_history,
            include_audience_metrics=include_audience_metrics,
        )

    @server.tool(
        name="list_media",
        description=(
            "List and filter media inventory records with structured filters (city, category, "
            "media_type, sub_type/lighting, orientation, owner, sync status) with pagination."
        ),
    )
    async def list_media(
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
        return await list_media_handler(
            city=city,
            category=category,
            media_type=media_type,
            sub_type=sub_type,
            orientation=orientation,
            media_owner=media_owner,
            is_synced=is_synced,
            admavin_sync_status=admavin_sync_status,
            offset=offset,
            limit=limit,
        )

    @server.tool(
        name="get_media_statistics",
        description=(
            "Calculate aggregate statistics across media inventory: total sites, active cities, "
            "media types, cost metrics (avg, min, max), audience reach totals, and optional "
            "categorical breakdowns by 'city', 'media_type', 'category', or 'media_owner'."
        ),
    )
    async def get_media_statistics(
        city: str = "",
        media_type: str = "",
        breakdown_by: str = "",
    ) -> str:
        return await get_media_statistics_handler(
            city=city,
            media_type=media_type,
            breakdown_by=breakdown_by,
        )

    @server.tool(
        name="get_media_asset",
        description=(
            "Retrieve the photograph asset reference and generate a short-lived S3 presigned URL "
            "for a media site by its inventory code or UUID. Does not expose AWS credentials."
        ),
    )
    async def get_media_asset(
        identifier: str,
        expires_in: int = 900,
    ) -> str:
        return await get_media_asset_handler(
            identifier=identifier,
            expires_in=expires_in,
        )

    @server.tool(
        name="find_related_media",
        description=(
            "Discover related or nearby media sites using geographic proximity from a reference "
            "site or GPS coordinates (latitude, longitude) within a radius (km). Returns distance."
        ),
    )
    async def find_related_media(
        reference_identifier: str = "",
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float = 5.0,
        same_media_type: bool = False,
        limit: int = 10,
    ) -> str:
        return await find_related_media_handler(
            reference_identifier=reference_identifier,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            same_media_type=same_media_type,
            limit=limit,
        )
