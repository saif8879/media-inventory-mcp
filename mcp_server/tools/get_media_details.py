from __future__ import annotations

import json
import logging
from typing import Any

from mcp_server.db import get_session
from mcp_server.schemas.common import StandardResponse
from mcp_server.services.media_service import MediaInventoryService

logger = logging.getLogger("mcp_server.tools.get_media_details")


async def get_media_details_handler(
    identifier: str,
    include_price_history: bool = True,
    include_audience_metrics: bool = True,
) -> str:
    """Retrieve comprehensive details for a specific media inventory site

    by its unique inventory code (e.g. 'MI1') or UUID id, including specifications,
    price quotation history, and AdMavin audience demographics.
    """
    if not identifier or not identifier.strip():
        return StandardResponse.error_response(
            code="INVALID_ARGUMENT",
            message="Identifier (inventory_code or UUID) must not be empty",
        ).model_dump_json()

    try:
        async with get_session() as session:
            service = MediaInventoryService(session)
            item = await service.get_media_by_identifier(
                identifier=identifier.strip(),
                include_price_history=include_price_history,
                include_audience_metrics=include_audience_metrics,
            )
            if not item:
                return StandardResponse.error_response(
                    code="ITEM_NOT_FOUND",
                    message=f"Media inventory site with identifier '{identifier}' was not found",
                    details={"identifier": identifier},
                ).model_dump_json()

            return StandardResponse.success_response(data=item).model_dump_json()
    except Exception as exc:
        logger.exception("get_media_details_failed")
        return StandardResponse.error_response(
            code="RETRIEVAL_ERROR",
            message=f"Failed to retrieve media details: {str(exc)}",
        ).model_dump_json()
