from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from mcp_server.config import get_settings
from mcp_server.oauth.tokens import issue_access_token
from mcp_server.server import create_app


def _access_token() -> str:
    settings = get_settings()
    public = settings.mcp_public_url.rstrip("/")
    return issue_access_token(
        secret=settings.oauth_jwt_secret,
        issuer=public,
        subject="google-subject",
        email="person@wrap2earn.com",
        hosted_domain=settings.google_hosted_domain,
        client_id="test-client",
        audiences=[f"{public}/mcp", f"{public}/sse"],
        ttl_seconds=3600,
    )


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
async def test_streamable_http_initialize(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret-test-key")
    monkeypatch.setenv("MCP_SERVER_HOST", "0.0.0.0")
    get_settings.cache_clear()
    app = create_app(oauth_database_url="sqlite+aiosqlite://")
    token = _access_token()

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0.0.1"},
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost:8090"
        ) as client:
            missing = await client.post("/mcp", json=payload)
            assert missing.status_code == 401

            res = await client.post("/mcp", json=payload, headers=headers)
            assert res.status_code == 200
            assert "media-inventory" in res.text


@pytest.mark.asyncio
async def test_auth_middleware_permits_valid_credentials(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret-test-key")
    get_settings.cache_clear()
    app = create_app()
    token = _access_token()

    # Add a lightweight test route to verify pass-through
    @app.get("/api/test-auth-verify")
    def verify_auth():
        return {"authorized": True}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8090"
    ) as client:
        r_bearer = await client.get(
            "/api/test-auth-verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_bearer.status_code == 200
        assert r_bearer.json() == {"authorized": True}

        r_hdr = await client.get(
            "/api/test-auth-verify",
            headers={"X-MCP-Key": "secret-test-key"},
        )
        assert r_hdr.status_code == 401

        r_query = await client.get("/api/test-auth-verify?token=secret-test-key")
        assert r_query.status_code == 401

        r_legacy = await client.get(
            "/api/test-auth-verify",
            headers={"Authorization": "Bearer secret-test-key"},
        )
        assert r_legacy.status_code == 401
