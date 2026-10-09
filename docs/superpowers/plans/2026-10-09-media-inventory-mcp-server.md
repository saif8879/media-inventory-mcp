# Media Inventory MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-ready, independently deployable Python Model Context Protocol (MCP) server for Media Inventory that allows AI clients to search, retrieve, analyze, and inspect OOH media inventory, quotation history, AdMavin audience metrics, and private S3 assets via short-lived presigned URLs.

**Architecture:** A standalone FastAPI + Starlette SSE application using the official Python MCP SDK (`mcp`) with FastMCP / low-level server integration. Connects asynchronously to PostgreSQL using SQLAlchemy 2.0 and boto3 for private S3 asset presigning. Secured via Bearer token authentication middleware.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, MCP Python SDK (`mcp>=1.0.0`), SQLAlchemy 2.0 (`asyncpg`), Pydantic v2, boto3, pytest, pytest-asyncio, httpx.

## Global Constraints

- Do not modify or rewrite the existing FastAPI backend or Next.js frontend code in `/Users/saifidrisi/Documents/media-inventory`.
- Reuse existing database schemas (`media_inventory`, `media_inventory_price_history`, `admavin_media_inventory`) without inventing tables or columns.
- Keep S3 bucket (`buzzomni-media-inventory`) private; only expose assets via short-lived presigned URLs (default 900s TTL). Never expose AWS credentials or internal connection strings.
- Enforce strict parameter bounds (`limit` max 100) and structured responses (`{success, data, pagination, error}`).
- Do not register any write/mutation tools until explicit authorization and confirmation workflows are designed.
- MCP server must run on a configurable port (`MCP_SERVER_PORT`, default 8090).

---

### Task 1: Project Environment & Configuration Setup

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `mcp_server/__init__.py`
- Create: `mcp_server/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Environment variables (`DATABASE_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_BUCKET`, `AWS_DEFAULT_REGION`, `MCP_API_KEY`, `MCP_SERVER_PORT`).
- Produces: `mcp_server.config.get_settings() -> Settings` providing validated settings object.

- [ ] **Step 1: Write test for configuration loading**

```python
# tests/test_config.py
import os
from mcp_server.config import Settings

def test_settings_default_values(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("MCP_API_KEY", "test-secret-key-12345")
    settings = Settings()
    assert settings.mcp_server_port == 8090
    assert settings.mcp_api_key == "test-secret-key-12345"
    assert settings.aws_s3_bucket == "buzzomni-media-inventory"
    assert settings.aws_s3_region == "ap-south-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py`
Expected: FAIL (No module named `mcp_server`)

- [ ] **Step 3: Implement minimal configuration and environment setup**

Create `requirements.txt`:
```
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
pydantic>=2.10.0
pydantic-settings>=2.7.0
sqlalchemy[asyncio]>=2.0.36
asyncpg>=0.30.0
boto3>=1.35.0
mcp>=1.0.0
httpx>=0.27.0
pytest>=8.0.0
pytest-asyncio>=0.24.0
```

Create `mcp_server/config.py`:
```python
from functools import lru_cache
from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        extra="ignore"
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
    presigned_url_expiry: int = Field(default=900, validation_alias="PRESIGNED_URL_EXPIRY")

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py`
Expected: PASS

- [ ] **Step 5: Commit configuration files**

```bash
git add pyproject.toml requirements.txt .env.example mcp_server/__init__.py mcp_server/config.py tests/test_config.py
git commit -m "feat(config): add project settings and env validation"
```

---

### Task 2: Database Connection & Common Schemas

**Files:**
- Create: `mcp_server/db.py`
- Create: `mcp_server/schemas/common.py`
- Test: `tests/test_common_schemas.py`

**Interfaces:**
- Consumes: `mcp_server.config.get_settings`
- Produces: `mcp_server.db.get_async_session()`, `mcp_server.schemas.common.StandardResponse[T]`

- [ ] **Step 1: Write test for StandardResponse serialization**

```python
# tests/test_common_schemas.py
from mcp_server.schemas.common import StandardResponse, PaginationMeta, ErrorPayload

def test_standard_response_success():
    resp = StandardResponse.success_response(
        data=[{"id": "1", "code": "MI1"}],
        pagination=PaginationMeta(offset=0, limit=20, total=1)
    )
    assert resp.success is True
    assert len(resp.data) == 1
    assert resp.pagination.total == 1
    assert resp.error is None

def test_standard_response_error():
    resp = StandardResponse.error_response(
        code="ITEM_NOT_FOUND",
        message="Item not found"
    )
    assert resp.success is False
    assert resp.data is None
    assert resp.error.code == "ITEM_NOT_FOUND"
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_common_schemas.py`
Expected: FAIL (Cannot import `StandardResponse`)

- [ ] **Step 3: Implement database session provider and common schemas**

Create `mcp_server/schemas/common.py`:
```python
from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel

T = TypeVar("T")

class PaginationMeta(BaseModel):
    offset: int = 0
    limit: int = 20
    total: int = 0

class ErrorPayload(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None

class StandardResponse(BaseModel, Generic[T]):
    success: bool
    data: Optional[T] = None
    pagination: Optional[PaginationMeta] = None
    error: Optional[ErrorPayload] = None

    @classmethod
    def success_response(
        cls,
        data: T,
        pagination: Optional[PaginationMeta] = None,
    ) -> "StandardResponse[T]":
        return cls(success=True, data=data, pagination=pagination, error=None)

    @classmethod
    def error_response(
        cls,
        code: str,
        message: str,
        details: Optional[Any] = None,
    ) -> "StandardResponse[None]":
        return cls(
            success=False,
            data=None,
            pagination=None,
            error=ErrorPayload(code=code, message=message, details=details),
        )
```

Create `mcp_server/db.py`:
```python
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from mcp_server.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_common_schemas.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_server/db.py mcp_server/schemas/common.py tests/test_common_schemas.py
git commit -m "feat(db,schemas): add async db session provider and standard response schemas"
```

---

### Task 3: S3 Presigned URL Service

**Files:**
- Create: `mcp_server/services/s3_service.py`
- Test: `tests/test_s3_service.py`

**Interfaces:**
- Consumes: `mcp_server.config.get_settings`
- Produces: `mcp_server.services.s3_service.generate_presigned_asset_url(key: str, expires_in: int = 900) -> str | None`

- [ ] **Step 1: Write test for S3 presigned URL generation with mocked boto3**

```python
# tests/test_s3_service.py
from unittest.mock import MagicMock
from mcp_server.services.s3_service import S3AssetService

def test_generate_presigned_url_valid_key(monkeypatch):
    mock_boto_client = MagicMock()
    mock_boto_client.generate_presigned_url.return_value = "https://s3.amazonaws.com/test?sig=123"
    
    service = S3AssetService(client=mock_boto_client, bucket="test-bucket")
    url = service.generate_presigned_url("media-inventory/MI1/test.jpg", expires_in=600)
    
    assert url == "https://s3.amazonaws.com/test?sig=123"
    mock_boto_client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "test-bucket", "Key": "media-inventory/MI1/test.jpg"},
        ExpiresIn=600,
    )

def test_generate_presigned_url_invalid_or_external_url():
    service = S3AssetService(client=MagicMock(), bucket="test-bucket")
    assert service.generate_presigned_url(None) is None
    assert service.generate_presigned_url("") is None
    # External URLs (e.g. google drive links) are returned as-is
    ext_url = "https://drive.google.com/file/d/xyz"
    assert service.generate_presigned_url(ext_url) == ext_url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_s3_service.py`
Expected: FAIL

- [ ] **Step 3: Implement S3 service**

Create `mcp_server/services/s3_service.py`:
```python
import boto3
from typing import Optional
from mcp_server.config import get_settings

class S3AssetService:
    def __init__(self, client=None, bucket: Optional[str] = None):
        settings = get_settings()
        self.bucket = bucket or settings.aws_s3_bucket
        if client:
            self._client = client
        else:
            kwargs = {"region_name": settings.aws_s3_region}
            if settings.aws_access_key_id and settings.aws_secret_access_key:
                kwargs["aws_access_key_id"] = settings.aws_access_key_id
                kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
            self._client = boto3.client("s3", **kwargs)

    def generate_presigned_url(self, image_key: Optional[str], expires_in: int = 900) -> Optional[str]:
        if not image_key or not image_key.strip():
            return None
        cleaned = image_key.strip()
        # If it's already an HTTP URL (external image or google drive link), return as-is
        if cleaned.startswith(("http://", "https://")):
            return cleaned

        normalized_key = cleaned.lstrip("/")
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": normalized_key},
            ExpiresIn=min(max(expires_in, 60), 3600),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_s3_service.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_server/services/s3_service.py tests/test_s3_service.py
git commit -m "feat(s3): implement safe presigned url asset service"
```

---

### Task 4: Media Inventory Query Service

**Files:**
- Create: `mcp_server/services/media_service.py`
- Test: `tests/test_media_service.py`

**Interfaces:**
- Consumes: `mcp_server.db.get_session`, SQLAlchemy tables (`media_inventory`, `admavin_media_inventory`, `media_inventory_price_history`).
- Produces: Functions for `search_media`, `get_details`, `list_media`, `get_statistics`, `find_related`.

- [ ] **Step 1: Write test for search and details logic using mocked DB session**

```python
# tests/test_media_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from mcp_server.services.media_service import MediaInventoryService

@pytest.mark.asyncio
async def test_get_by_identifier_missing():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.one_or_none.return_value = None
    mock_session.execute.return_value = mock_result
    
    service = MediaInventoryService(mock_session)
    result = await service.get_media_by_identifier("NONEXISTENT")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_media_service.py`
Expected: FAIL

- [ ] **Step 3: Implement MediaInventoryService**

Create `mcp_server/services/media_service.py`:
Handles SQL queries with parameterized statements, outer joins with AdMavin metrics, price history queries, and Haversine distance calculations for `find_related_media`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_media_service.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_server/services/media_service.py tests/test_media_service.py
git commit -m "feat(service): implement async media inventory query service"
```

---

### Task 5: Implement MCP Read-Only Tools

**Files:**
- Create: `mcp_server/tools/__init__.py`
- Create: `mcp_server/tools/search_media.py`
- Create: `mcp_server/tools/get_media_details.py`
- Create: `mcp_server/tools/list_media.py`
- Create: `mcp_server/tools/get_media_statistics.py`
- Create: `mcp_server/tools/get_media_asset.py`
- Create: `mcp_server/tools/find_related_media.py`
- Test: `tests/test_mcp_tools.py`

**Interfaces:**
- Consumes: `MediaInventoryService`, `S3AssetService`, `FastMCP` or MCP Server instance.
- Produces: 6 registered MCP tools returning valid `StandardResponse` JSON strings.

- [ ] **Step 1: Write test for tool schemas and execution**

```python
# tests/test_mcp_tools.py
import pytest
import json
from unittest.mock import AsyncMock, patch
from mcp_server.tools.search_media import search_media_handler

@pytest.mark.asyncio
async def test_search_media_handler():
    with patch("mcp_server.tools.search_media.MediaInventoryService") as mock_srv_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.search.return_value = ([], 0)
        
        result_json = await search_media_handler(query="billboard", limit=10)
        result = json.loads(result_json)
        assert result["success"] is True
        assert result["pagination"]["total"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_tools.py`
Expected: FAIL

- [ ] **Step 3: Implement all 6 tool handlers**

Implement `search_media`, `get_media_details`, `list_media`, `get_media_statistics`, `get_media_asset`, and `find_related_media`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_tools.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_server/tools/ tests/test_mcp_tools.py
git commit -m "feat(tools): register read-only media inventory MCP tools"
```

---

### Task 6: Server Initialization, Authentication Middleware & SSE Transport

**Files:**
- Create: `mcp_server/auth.py`
- Create: `mcp_server/server.py`
- Test: `tests/test_mcp_auth.py`
- Test: `tests/test_server_transport.py`

**Interfaces:**
- Consumes: MCP tool definitions, `get_settings`.
- Produces: Running FastAPI application with Starlette SSE endpoint and `/health` route.

- [ ] **Step 1: Write test for authentication enforcement**

```python
# tests/test_mcp_auth.py
import pytest
from httpx import AsyncClient, ASGITransport
from mcp_server.server import app

@pytest.mark.asyncio
async def test_health_check_public():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_mcp_endpoint_requires_auth(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret-test-key")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Without auth header
        res = await client.get("/sse")
        assert res.status_code == 401
        
        # With valid auth header
        res_auth = await client.get("/sse", headers={"Authorization": "Bearer secret-test-key"})
        assert res_auth.status_code != 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_auth.py`
Expected: FAIL

- [ ] **Step 3: Implement auth middleware and server.py**

Create `mcp_server/auth.py` validating `Bearer` token or `x-api-key`.
Create `mcp_server/server.py` creating the FastAPI app, registering tools onto MCP Server, and mounting SSE transport.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_auth.py tests/test_server_transport.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_server/auth.py mcp_server/server.py tests/test_mcp_auth.py tests/test_server_transport.py
git commit -m "feat(server): setup FastAPI SSE transport and authentication middleware"
```

---

### Task 7: Client Integration Testing, Deployment & Verification

**Files:**
- Create: `tests/test_client_integration.py`
- Create: `deploy/media-inventory-mcp.service`
- Create: `deploy/deploy.sh`
- Create: `README.md`

- [ ] **Step 1: Write end-to-end MCP client integration test**
Using MCP SDK's client session over transport to invoke registered tools.

- [ ] **Step 2: Execute integration test suite**

Run: `pytest tests/test_client_integration.py`
Expected: PASS

- [ ] **Step 3: Document deployment instructions and client configurations in README.md**

- [ ] **Step 4: Commit**

```bash
git add tests/test_client_integration.py deploy/ README.md
git commit -m "docs,deploy: add systemd service, deployment scripts and client integration tests"
```
