from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt


class TokenRejected(Exception):
    """Access token or login state could not be verified."""


def issue_access_token(
    *,
    secret: str,
    issuer: str,
    subject: str,
    email: str,
    hosted_domain: str,
    client_id: str,
    audiences: list[str],
    ttl_seconds: int,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": issuer,
        "sub": subject,
        "aud": audiences,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "email": email,
        "hd": hosted_domain,
        "client_id": client_id,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(
    token: str,
    *,
    secret: str,
    issuer: str,
    audiences: list[str],
) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            audience=audiences,
        )
    except jwt.PyJWTError as exc:
        raise TokenRejected("invalid access token") from exc
    return claims


def issue_state_token(payload: dict[str, Any], *, secret: str, ttl_seconds: int) -> str:
    now = datetime.now(UTC)
    body = {
        **payload,
        "typ": "oauth_state",
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(body, secret, algorithm="HS256")


def read_state_token(token: str, *, secret: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise TokenRejected("invalid login state") from exc
    if claims.get("typ") != "oauth_state":
        raise TokenRejected("invalid login state")
    return claims
