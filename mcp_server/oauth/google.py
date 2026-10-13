from __future__ import annotations

import asyncio
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient


class GoogleVerificationError(Exception):
    """Google did not return a usable identity token."""


class GoogleOAuth:
    """Google is the identity provider. This server still issues MCP tokens."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        hosted_domain: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._hosted_domain = hosted_domain
        self._jwks = PyJWKClient("https://www.googleapis.com/oauth2/v3/certs")

    def authorization_url(self, *, state: str, nonce: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "hd": self._hosted_domain,
                "state": state,
                "nonce": nonce,
                "prompt": "select_account",
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    async def exchange(self, code: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": self._redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        if response.status_code != 200:
            raise GoogleVerificationError("google token exchange failed")
        id_token = response.json().get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise GoogleVerificationError("google did not return an id token")
        return await asyncio.to_thread(self._decode_id_token, id_token)

    def _decode_id_token(self, id_token: str) -> dict:
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(id_token)
            return jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer="https://accounts.google.com",
            )
        except jwt.PyJWTError as exc:
            raise GoogleVerificationError("google id token rejected") from exc
