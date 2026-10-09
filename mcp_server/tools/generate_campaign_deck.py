from __future__ import annotations

import logging
from typing import Any

from mcp_server.db import get_session
from mcp_server.schemas.common import StandardResponse
from mcp_server.services.deck_service import DeckBuilderService
from mcp_server.services.media_service import MediaInventoryService

logger = logging.getLogger("mcp_server.tools.generate_campaign_deck")


async def generate_campaign_deck_handler(
    site_identifiers: list[str],
    campaign_title: str = "Campaign Proposal",
    client_name: str = "",
    theme: str = "editorial",
    include_commercials: bool = True,
    include_audience_metrics: bool = True,
    expires_in: int = 900,
) -> str:
    """Generate an Out-of-Home (OOH) campaign presentation deck in 16:9 widescreen PPTX format

    for selected media inventory sites. Embeds site photographs, technical dimensions,
    location details, audience metrics, and quotation costs. Delivers both local file path
    and private S3 presigned download URL.
    """
    cleaned_identifiers = [
        str(ident).strip()
        for ident in (site_identifiers or [])
        if str(ident).strip()
    ]

    if not cleaned_identifiers:
        return StandardResponse.error_response(
            code="NO_VALID_SITES",
            message="No valid site identifiers provided to generate campaign deck.",
        ).model_dump_json()

    valid_sites: list[dict[str, Any]] = []
    warnings: list[str] = []

    try:
        async with get_session() as session:
            service = MediaInventoryService(session)
            for ident in cleaned_identifiers:
                site = await service.get_media_by_identifier(
                    identifier=ident,
                    include_price_history=True,
                    include_audience_metrics=include_audience_metrics,
                )
                if site is None:
                    warnings.append(f"Site '{ident}' not found in inventory and was skipped.")
                else:
                    valid_sites.append(site)

        if not valid_sites:
            return StandardResponse.error_response(
                code="NO_VALID_SITES",
                message="None of the specified site identifiers were found in the media inventory.",
                details={"requested_sites": site_identifiers, "warnings": warnings},
            ).model_dump_json()

        deck_service = DeckBuilderService()
        deck_bytes, summary = deck_service.build_deck(
            sites=valid_sites,
            campaign_title=campaign_title or "Campaign Proposal",
            client_name=client_name or "",
            theme=theme or "editorial",
            include_commercials=include_commercials,
            include_audience_metrics=include_audience_metrics,
        )

        upload_result = deck_service.save_and_upload(
            deck_bytes=deck_bytes,
            file_slug=campaign_title or "proposal",
            expires_in=expires_in,
        )

        data = {
            "file_name": upload_result["file_name"],
            "local_file_path": upload_result["local_file_path"],
            "s3_download_url": upload_result["s3_download_url"],
            "expires_in_seconds": upload_result["expires_in_seconds"],
            "site_count": summary["site_count"],
            "theme": theme,
            "summary": summary,
            "warnings": warnings,
        }

        return StandardResponse.success_response(data=data).model_dump_json()
    except Exception as exc:
        logger.exception("generate_campaign_deck_failed")
        return StandardResponse.error_response(
            code="DECK_GENERATION_ERROR",
            message=f"Failed to generate campaign deck: {str(exc)}",
        ).model_dump_json()
