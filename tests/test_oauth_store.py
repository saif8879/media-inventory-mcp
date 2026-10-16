import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from mcp_server.oauth.store import AuthCode, RefreshReuse, SqlOAuthStore

pytestmark = pytest.mark.asyncio


def _code() -> AuthCode:
    return AuthCode(
        client_id="client-1",
        redirect_uri="http://127.0.0.1:9/callback",
        code_challenge="challenge",
        google_sub="google-subject",
        email="person@wrap2earn.com",
        hosted_domain="wrap2earn.com",
    )


@pytest.fixture
async def store() -> SqlOAuthStore:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    oauth_store = SqlOAuthStore(async_sessionmaker(engine, expire_on_commit=False))
    await oauth_store.setup(engine)
    yield oauth_store
    await engine.dispose()


async def test_authorization_code_can_be_used_once(store: SqlOAuthStore) -> None:
    await store.save_auth_code("raw-code", _code(), ttl_seconds=60)
    first = await store.consume_auth_code("raw-code")
    second = await store.consume_auth_code("raw-code")
    assert first is not None
    assert first.email == "person@wrap2earn.com"
    assert second is None


async def test_expired_authorization_code_is_rejected(store: SqlOAuthStore) -> None:
    await store.save_auth_code("raw-code", _code(), ttl_seconds=-1)
    assert await store.consume_auth_code("raw-code") is None


async def test_refresh_token_rotation_rejects_reuse(store: SqlOAuthStore) -> None:
    record = _code()
    await store.save_refresh_token(
        "old-token",
        client_id=record.client_id,
        google_sub=record.google_sub,
        email=record.email,
        hosted_domain=record.hosted_domain,
        ttl_seconds=3600,
    )
    rotated = await store.rotate_refresh_token("old-token", "new-token", ttl_seconds=3600)
    assert rotated is not None
    assert rotated.email == "person@wrap2earn.com"

    with pytest.raises(RefreshReuse):
        await store.rotate_refresh_token("old-token", "newer-token", ttl_seconds=3600)

    with pytest.raises(RefreshReuse):
        await store.rotate_refresh_token("new-token", "another-token", ttl_seconds=3600)


async def test_unknown_refresh_token_does_not_revoke_family(store: SqlOAuthStore) -> None:
    await store.save_refresh_token(
        "live-token",
        client_id="client-1",
        google_sub="google-subject",
        email="person@wrap2earn.com",
        hosted_domain="wrap2earn.com",
        ttl_seconds=3600,
    )
    assert await store.rotate_refresh_token("missing", "replacement", ttl_seconds=3600) is None
    rotated = await store.rotate_refresh_token("live-token", "replacement", ttl_seconds=3600)
    assert rotated is not None


async def test_registered_client_keeps_redirect_uris(store: SqlOAuthStore) -> None:
    await store.save_client(
        "client-1",
        "Cursor",
        ["http://127.0.0.1:9/callback"],
    )
    client = await store.get_client("client-1")
    assert client is not None
    assert client.redirect_uris == ["http://127.0.0.1:9/callback"]
    assert await store.get_client("missing") is None
