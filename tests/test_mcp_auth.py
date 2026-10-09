from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from mcp_server.config import get_settings
from mcp_server.server import create_app


@pytest.fixture(autouse=True)
def reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_health_check_public(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret-test-key")
    get_settings.cache_clear()
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8090"
    ) as client:
        res = await client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["service"] == "media-inventory-mcp"
        assert "tools" in data


@pytest.mark.asyncio
async def test_mcp_endpoint_rejects_without_auth(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret-test-key")
    get_settings.cache_clear()
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8090"
    ) as client:
        res = await client.get("/sse")
        assert res.status_code == 401
        assert "Unauthorized" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_mcp_endpoint_rejects_invalid_key(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret-test-key")
    get_settings.cache_clear()
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8090"
    ) as client:
        res = await client.get(
            "/sse", headers={"Authorization": "Bearer wrong-key"}
        )
        assert res.status_code == 401
        assert "Unauthorized" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_auth_middleware_permits_valid_credentials(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret-test-key")
    get_settings.cache_clear()
    app = create_app()

    # Add a lightweight test route to verify pass-through
    @app.get("/api/test-auth-verify")
    def verify_auth():
        return {"authorized": True}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8090"
    ) as client:
        # Bearer token
        r_bearer = await client.get(
            "/api/test-auth-verify",
            headers={"Authorization": "Bearer secret-test-key"},
        )
        assert r_bearer.status_code == 200
        assert r_bearer.json() == {"authorized": True}

        # X-MCP-Key header
        r_hdr = await client.get(
            "/api/test-auth-verify",
            headers={"X-MCP-Key": "secret-test-key"},
        )
        assert r_hdr.status_code == 200
        assert r_hdr.json() == {"authorized": True}

        # Query param token
        r_query = await client.get("/api/test-auth-verify?token=secret-test-key")
        assert r_query.status_code == 200
        assert r_query.json() == {"authorized": True}
