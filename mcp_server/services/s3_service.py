from __future__ import annotations

import logging
from pathlib import PurePath
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from mcp_server.config import get_settings

logger = logging.getLogger("mcp_server.s3")


class S3AssetService:
    def __init__(self, client=None, bucket: str | None = None) -> None:
        settings = get_settings()
        self.bucket = bucket or settings.aws_s3_bucket
        if client is not None:
            self._client = client
        else:
            kwargs: dict[str, Any] = {"region_name": settings.aws_s3_region}
            if settings.aws_access_key_id and settings.aws_secret_access_key:
                kwargs["aws_access_key_id"] = settings.aws_access_key_id
                kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
            self._client = boto3.client("s3", **kwargs)

    def generate_presigned_url(
        self, image_key: str | None, expires_in: int = 900
    ) -> str | None:
        if not image_key or not image_key.strip():
            return None

        cleaned = image_key.strip()
        # If it's an external URL (Google Drive, CDN, or third party link), return as-is
        if cleaned.startswith(("http://", "https://")):
            return cleaned

        normalized_key = cleaned.lstrip("/")
        if ".." in normalized_key.split("/"):
            logger.warning("directory_traversal_attempt_in_key", extra={"key": image_key})
            return None

        # Clamp expiry between 60s and 3600s (1 hour)
        safe_expiry = min(max(expires_in, 60), 3600)

        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": normalized_key},
                ExpiresIn=safe_expiry,
            )
        except (ClientError, BotoCoreError) as exc:
            logger.error("s3_presigned_url_generation_failed", extra={"error": str(exc), "key": normalized_key})
            return None

    def get_asset_info(
        self, image_key: str | None, expires_in: int = 900
    ) -> dict[str, Any] | None:
        if not image_key or not image_key.strip():
            return None

        cleaned = image_key.strip()
        is_external = cleaned.startswith(("http://", "https://"))
        url = self.generate_presigned_url(cleaned, expires_in=expires_in)
        if not url:
            return None

        ext = PurePath(cleaned).suffix.lstrip(".").lower() or "unknown"
        return {
            "key": cleaned if not is_external else None,
            "url": url,
            "is_presigned": not is_external,
            "format": ext,
            "expires_in_seconds": expires_in if not is_external else None,
        }
