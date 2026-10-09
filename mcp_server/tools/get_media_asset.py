from __future__ import annotations

import json
import logging
from typing import Any

from mcp_server.config import get_settings
from mcp_server.db import get_session
from mcp_server.schemas.common import StandardResponse
from mcp_server.services.media_service import MediaInventoryService
from mcp_server.services.s3_service import S3AssetService

logger = logging.getLogger("mcp_server.tools.get_media_asset")


async def get_media_asset_handler(
    identifier: str,
    expires_in: int = 900,
) -> str:
    """Retrieve the photograph asset reference and short-lived S3 presigned URL

    for a media inventory site by inventory_code (e.g. 'MI1') or UUID id.
    Does not expose AWS credentials.
    """
    if not identifier or not identifier.strip():
        return StandardResponse.error_response(
            code="INVALID_ARGUMENT",
            message="Identifier (inventory_code or UUID) must not be empty",
        ).model_dump_json()

    try:
        async with get_session() as session:
            service = MediaInventoryService(session)
            media = await service.get_media_by_identifier(
                identifier.strip(),
                include_price_history=False,
                include_audience_metrics=False,
            )
            if not media:
                return StandardResponse.error_response(
                    code="ITEM_NOT_FOUND",
                    message=f"Media inventory site with identifier '{identifier}' was not found",
                    details={"identifier": identifier},
                ).model_dump_json()

            image_url = media.get("image_url")
            if not image_url or not image_url.strip():
                return StandardResponse.error_response(
                    code="ASSET_NOT_FOUND",
                    message=f"Media site '{identifier}' has no photo asset associated with it",
                    details={"identifier": identifier},
                ).model_dump_json()

            s3_service = S3AssetService()
            asset_info = s3_service.get_asset_info(image_url, expires_in=expires_in)
            if not asset_info:
                return StandardResponse.error_response(
                    code="ASSET_GENERATION_FAILED",
                    message=f"Failed to generate presigned asset URL for '{identifier}'",
                ).model_dump_json()

            return StandardResponse.success_response(data=asset_info).model_dump_json()
    except Exception as exc:
        logger.exception("get_media_asset_failed")
        return StandardResponse.error_response(
            code="STORAGE_ERROR",
            message=f"Failed to process media asset: {str(exc)}",
        ).model_dump_json()
