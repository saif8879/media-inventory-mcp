from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        extra="ignore",
    )

    # Server configuration
    mcp_server_port: int = Field(default=8090, validation_alias="MCP_SERVER_PORT")
    mcp_server_host: str = Field(default="0.0.0.0", validation_alias="MCP_SERVER_HOST")
    mcp_api_key: str = Field(default="", validation_alias="MCP_API_KEY")

    # Database
    database_url: str = Field(..., validation_alias="DATABASE_URL")

    # AWS S3 Storage
    aws_access_key_id: str = Field(default="", validation_alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(default="", validation_alias="AWS_SECRET_ACCESS_KEY")
    aws_s3_bucket: str = Field(
        default="buzzomni-media-inventory",
        validation_alias=AliasChoices("AWS_BUCKET", "AWS_S3_BUCKET"),
    )
    aws_s3_region: str = Field(
        default="ap-south-1",
        validation_alias=AliasChoices("AWS_DEFAULT_REGION", "AWS_S3_REGION"),
    )
    aws_s3_base_url: str = Field(
        default="https://buzzomni-media-inventory.s3.ap-south-1.amazonaws.com/",
        validation_alias="AWS_S3_BASE_URL",
    )
    presigned_url_expiry: int = Field(default=900, validation_alias="PRESIGNED_URL_EXPIRY")


@lru_cache
def get_settings() -> Settings:
    return Settings()
