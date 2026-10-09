from __future__ import annotations

from unittest.mock import MagicMock
from mcp_server.services.s3_service import S3AssetService


def test_generate_presigned_url_valid_s3_key():
    mock_boto_client = MagicMock()
    mock_boto_client.generate_presigned_url.return_value = (
        "https://buzzomni-media-inventory.s3.ap-south-1.amazonaws.com/test.jpg?sig=xyz"
    )

    service = S3AssetService(client=mock_boto_client, bucket="test-bucket")
    url = service.generate_presigned_url("media-inventory/MI1/test.jpg", expires_in=600)

    assert url == "https://buzzomni-media-inventory.s3.ap-south-1.amazonaws.com/test.jpg?sig=xyz"
    mock_boto_client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "test-bucket", "Key": "media-inventory/MI1/test.jpg"},
        ExpiresIn=600,
    )


def test_generate_presigned_url_external_url():
    mock_boto_client = MagicMock()
    service = S3AssetService(client=mock_boto_client, bucket="test-bucket")

    ext_url = "https://drive.google.com/file/d/123/view"
    assert service.generate_presigned_url(ext_url) == ext_url
    mock_boto_client.generate_presigned_url.assert_not_called()


def test_generate_presigned_url_empty_or_none():
    mock_boto_client = MagicMock()
    service = S3AssetService(client=mock_boto_client, bucket="test-bucket")

    assert service.generate_presigned_url(None) is None
    assert service.generate_presigned_url("") is None
    assert service.generate_presigned_url("   ") is None
    mock_boto_client.generate_presigned_url.assert_not_called()


def test_get_asset_info():
    mock_boto_client = MagicMock()
    mock_boto_client.generate_presigned_url.return_value = "https://presigned-url"

    service = S3AssetService(client=mock_boto_client, bucket="test-bucket")
    info = service.get_asset_info("media-inventory/MI10/photo.png", expires_in=900)

    assert info is not None
    assert info["key"] == "media-inventory/MI10/photo.png"
    assert info["url"] == "https://presigned-url"
    assert info["is_presigned"] is True
    assert info["format"] == "png"
    assert info["expires_in_seconds"] == 900
