from __future__ import annotations

import pytest
from mcp_server.config import Settings


def test_settings_custom_values(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("MCP_API_KEY", "test-secret-key-12345")
    monkeypatch.setenv("MCP_SERVER_PORT", "9090")
    settings = Settings()
    assert settings.mcp_server_port == 9090
    assert settings.mcp_api_key == "test-secret-key-12345"
    assert settings.aws_s3_bucket == "buzzomni-media-inventory"
    assert settings.aws_s3_region == "ap-south-1"


def test_cli_main_argparse(monkeypatch):
    from unittest.mock import patch
    from mcp_server.__main__ import main

    monkeypatch.setattr("sys.argv", ["mcp_server", "--transport", "stdio"])
    with patch("mcp_server.__main__.create_mcp_server") as mock_srv_cls:
        mock_srv = mock_srv_cls.return_value
        main()
        mock_srv.run.assert_called_once_with(transport="stdio")

