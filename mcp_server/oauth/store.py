from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from mcp_server.oauth.models import OAuthAuthCode, OAuthBase, OAuthClient, OAuthRefreshToken


class RefreshReuse(Exception):
    """A rotated refresh token was presented again."""


@dataclass(frozen=True)
class AuthCode:
    client_id: str
    redirect_uri: str
    code_challenge: str
    google_sub: str
    email: str
    hosted_domain: str


@dataclass(frozen=True)
class RegisteredClient:
    client_id: str
    client_name: str
    redirect_uris: list[str]


@dataclass(frozen=True)
class RefreshGrant:
    client_id: str
    google_sub: str
    email: str
    hosted_domain: str


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SqlOAuthStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._sessions = sessions

    def bind(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def setup(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            await conn.run_sync(OAuthBase.metadata.create_all)

    async def save_client(self, client_id: str, client_name: str, redirect_uris: list[str]) -> None:
        async with self._sessions() as session:
            session.add(
                OAuthClient(
                    client_id=client_id,
                    client_name=client_name,
                    redirect_uris=list(redirect_uris),
                )
            )
            await session.commit()

    async def get_client(self, client_id: str) -> RegisteredClient | None:
        async with self._sessions() as session:
            row = await session.get(OAuthClient, client_id)
            if row is None:
                return None
            return RegisteredClient(
                client_id=row.client_id,
                client_name=row.client_name,
                redirect_uris=list(row.redirect_uris),
            )

    async def save_auth_code(self, raw_code: str, code: AuthCode, ttl_seconds: int) -> None:
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        async with self._sessions() as session:
            session.add(
                OAuthAuthCode(
                    code_hash=_hash(raw_code),
                    client_id=code.client_id,
                    redirect_uri=code.redirect_uri,
                    code_challenge=code.code_challenge,
                    google_sub=code.google_sub,
                    email=code.email,
                    hosted_domain=code.hosted_domain,
                    expires_at=expires_at,
                )
            )
            await session.commit()

    async def consume_auth_code(self, raw_code: str) -> AuthCode | None:
        now = datetime.now(UTC)
        async with self._sessions() as session:
            result = await session.execute(
                update(OAuthAuthCode)
                .where(
                    OAuthAuthCode.code_hash == _hash(raw_code),
                    OAuthAuthCode.used_at.is_(None),
                    OAuthAuthCode.expires_at > now,
                )
                .values(used_at=now)
                .returning(OAuthAuthCode)
            )
            row = result.scalar_one_or_none()
            await session.commit()
            if row is None:
                return None
            return AuthCode(
                client_id=row.client_id,
                redirect_uri=row.redirect_uri,
                code_challenge=row.code_challenge,
                google_sub=row.google_sub,
                email=row.email,
                hosted_domain=row.hosted_domain,
            )

    async def save_refresh_token(
        self,
        raw_token: str,
        *,
        client_id: str,
        google_sub: str,
        email: str,
        hosted_domain: str,
        ttl_seconds: int,
    ) -> None:
        async with self._sessions() as session:
            session.add(
                OAuthRefreshToken(
                    token_hash=_hash(raw_token),
                    client_id=client_id,
                    google_sub=google_sub,
                    email=email,
                    hosted_domain=hosted_domain,
                    expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
                )
            )
            await session.commit()

    async def rotate_refresh_token(
        self,
        raw_token: str,
        replacement: str,
        *,
        ttl_seconds: int,
        client_id: str | None = None,
    ) -> RefreshGrant | None:
        now = datetime.now(UTC)
        token_hash = _hash(raw_token)
        replacement_hash = _hash(replacement)
        conditions = [
            OAuthRefreshToken.token_hash == token_hash,
            OAuthRefreshToken.revoked_at.is_(None),
            OAuthRefreshToken.expires_at > now,
        ]
        if client_id is not None:
            conditions.append(OAuthRefreshToken.client_id == client_id)
        async with self._sessions() as session:
            result = await session.execute(
                update(OAuthRefreshToken)
                .where(*conditions)
                .values(revoked_at=now, replaced_by_hash=replacement_hash)
                .returning(OAuthRefreshToken)
            )
            current = result.scalar_one_or_none()
            if current is not None:
                session.add(
                    OAuthRefreshToken(
                        token_hash=replacement_hash,
                        client_id=current.client_id,
                        google_sub=current.google_sub,
                        email=current.email,
                        hosted_domain=current.hosted_domain,
                        expires_at=now + timedelta(seconds=ttl_seconds),
                    )
                )
                await session.commit()
                return RefreshGrant(
                    client_id=current.client_id,
                    google_sub=current.google_sub,
                    email=current.email,
                    hosted_domain=current.hosted_domain,
                )

            existing = await session.get(OAuthRefreshToken, token_hash)
            if existing is not None and existing.revoked_at is not None:
                await session.execute(
                    update(OAuthRefreshToken)
                    .where(
                        OAuthRefreshToken.client_id == existing.client_id,
                        OAuthRefreshToken.google_sub == existing.google_sub,
                        OAuthRefreshToken.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
                await session.commit()
                raise RefreshReuse("refresh token was already used")
            await session.rollback()
            return None
