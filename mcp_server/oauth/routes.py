from __future__ import annotations

import html
import logging
import secrets
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from mcp_server.config import Settings
from mcp_server.oauth.google import GoogleVerificationError
from mcp_server.oauth.identity import IdentityRejected, require_workspace_identity
from mcp_server.oauth.pkce import pkce_s256_valid
from mcp_server.oauth.redirects import redirect_uri_error
from mcp_server.oauth.store import AuthCode, RefreshReuse, SqlOAuthStore
from mcp_server.oauth.tokens import TokenRejected, issue_access_token, issue_state_token, read_state_token

logger = logging.getLogger("mcp_server.oauth")

AUTH_CODE_TTL_SECONDS = 60
STATE_TTL_SECONDS = 600


class GoogleLogin(Protocol):
    def authorization_url(self, *, state: str, nonce: str) -> str: ...

    async def exchange(self, code: str) -> dict: ...


def resource_audiences(public_url: str) -> list[str]:
    base = public_url.rstrip("/")
    return [f"{base}/mcp", f"{base}/sse"]


def register_oauth_routes(
    app: FastAPI,
    settings: Settings,
    store: SqlOAuthStore,
    google: GoogleLogin | None,
) -> None:
    public = settings.mcp_public_url.rstrip("/")
    audiences = resource_audiences(public)

    def metadata() -> dict[str, Any]:
        return {
            "issuer": public,
            "authorization_endpoint": f"{public}/authorize",
            "token_endpoint": f"{public}/token",
            "registration_endpoint": f"{public}/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["mcp"],
        }

    def protected_resource() -> dict[str, Any]:
        return {
            "resource": f"{public}/mcp",
            "authorization_servers": [public],
            "bearer_methods_supported": ["header"],
            "scopes_supported": ["mcp"],
        }

    @app.get("/.well-known/oauth-authorization-server")
    async def authorization_server_metadata() -> dict[str, Any]:
        return metadata()

    @app.get("/.well-known/oauth-protected-resource")
    async def protected_resource_metadata() -> dict[str, Any]:
        return protected_resource()

    @app.get("/.well-known/oauth-protected-resource/mcp")
    async def protected_resource_mcp() -> dict[str, Any]:
        return protected_resource()

    @app.get("/.well-known/oauth-protected-resource/sse")
    async def protected_resource_sse() -> dict[str, Any]:
        return protected_resource()

    @app.post("/register")
    async def register(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _oauth_error("invalid_client_metadata", "registration body must be JSON", 400)
        if not isinstance(body, dict):
            return _oauth_error("invalid_client_metadata", "registration body must be an object", 400)
        redirect_uris = body.get("redirect_uris")
        if not isinstance(redirect_uris, list) or not redirect_uris:
            return _oauth_error("invalid_redirect_uri", "redirect_uris is required", 400)
        for uri in redirect_uris:
            if not isinstance(uri, str) or redirect_uri_error(uri):
                return _oauth_error("invalid_redirect_uri", "redirect URI is not allowed", 400)
        auth_method = body.get("token_endpoint_auth_method", "none")
        if auth_method != "none":
            return _oauth_error(
                "invalid_client_metadata",
                "only public clients are supported",
                400,
            )
        client_name = body.get("client_name") or ""
        if not isinstance(client_name, str):
            client_name = ""
        client_id = secrets.token_urlsafe(24)
        await store.save_client(client_id, client_name, [str(uri) for uri in redirect_uris])
        return JSONResponse(
            status_code=201,
            content={
                "client_id": client_id,
                "client_name": client_name,
                "redirect_uris": redirect_uris,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )

    @app.get("/authorize", response_model=None)
    async def authorize(request: Request):
        if google is None:
            return _oauth_error("server_error", "Google OAuth is not configured", 503)
        client_id = request.query_params.get("client_id", "")
        redirect_uri = request.query_params.get("redirect_uri", "")
        client = await store.get_client(client_id) if client_id else None
        if client is None or redirect_uri not in client.redirect_uris:
            return _page(400, "This sign-in request is not from a registered client.")
        client_state = request.query_params.get("state", "")
        response_type = request.query_params.get("response_type", "")
        challenge = request.query_params.get("code_challenge", "")
        method = request.query_params.get("code_challenge_method", "")
        resource = request.query_params.get("resource", "")
        if response_type != "code" or not challenge or method != "S256":
            return _redirect_error(redirect_uri, "invalid_request", "PKCE S256 is required", client_state)
        if resource and resource not in audiences:
            return _redirect_error(redirect_uri, "invalid_target", "resource is not this server", client_state)
        nonce = secrets.token_urlsafe(16)
        state = issue_state_token(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": challenge,
                "client_state": client_state,
                "nonce": nonce,
                "resource": resource or audiences[0],
            },
            secret=settings.oauth_jwt_secret,
            ttl_seconds=STATE_TTL_SECONDS,
        )
        return RedirectResponse(google.authorization_url(state=state, nonce=nonce), status_code=302)

    @app.get("/auth/google/callback", response_model=None)
    async def google_callback(request: Request):
        if google is None:
            return _oauth_error("server_error", "Google OAuth is not configured", 503)
        if request.query_params.get("error"):
            return _page(403, "Google sign-in was cancelled.")
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        if not code or not state:
            return _page(400, "Google sign-in did not return a code.")
        try:
            pending = read_state_token(state, secret=settings.oauth_jwt_secret)
        except TokenRejected:
            return _page(400, "This sign-in attempt expired. Connect again from the client.")
        try:
            claims = await google.exchange(code)
        except GoogleVerificationError:
            logger.warning("google_id_token_rejected")
            return _page(403, "Google sign-in could not be verified.")
        if claims.get("nonce") != pending.get("nonce"):
            return _page(403, "Google sign-in could not be verified.")
        if not claims.get("sub"):
            return _page(403, "Google sign-in could not be verified.")
        try:
            require_workspace_identity(claims, settings.google_hosted_domain)
        except IdentityRejected as exc:
            logger.warning(
                "workspace_identity_rejected",
                extra={"email": claims.get("email", ""), "reason": str(exc)},
            )
            return _page(403, str(exc))
        raw_code = secrets.token_urlsafe(32)
        await store.save_auth_code(
            raw_code,
            AuthCode(
                client_id=str(pending["client_id"]),
                redirect_uri=str(pending["redirect_uri"]),
                code_challenge=str(pending["code_challenge"]),
                google_sub=str(claims["sub"]),
                email=str(claims["email"]),
                hosted_domain=str(claims["hd"]),
            ),
            ttl_seconds=AUTH_CODE_TTL_SECONDS,
        )
        return RedirectResponse(
            _with_query(
                str(pending["redirect_uri"]),
                {"code": raw_code, "state": str(pending.get("client_state") or "")},
            ),
            status_code=302,
        )

    @app.post("/token")
    async def token(request: Request) -> JSONResponse:
        form = await _form(request)
        grant_type = form.get("grant_type", "")
        client_id = form.get("client_id", "")
        if grant_type == "authorization_code":
            return await _authorization_code_grant(form, client_id)
        if grant_type == "refresh_token":
            return await _refresh_grant(form, client_id)
        return _oauth_error("unsupported_grant_type", "grant_type is not supported", 400)

    async def _authorization_code_grant(form: dict[str, str], client_id: str) -> JSONResponse:
        raw_code = form.get("code", "")
        redirect_uri = form.get("redirect_uri", "")
        verifier = form.get("code_verifier", "")
        if not raw_code or not client_id or not redirect_uri or not verifier:
            return _oauth_error("invalid_request", "code, client_id, redirect_uri, and code_verifier are required")
        granted = await store.consume_auth_code(raw_code)
        if granted is None:
            return _oauth_error("invalid_grant", "authorization code is invalid or already used")
        if granted.client_id != client_id or granted.redirect_uri != redirect_uri:
            return _oauth_error("invalid_grant", "authorization code does not match this client")
        if not pkce_s256_valid(verifier, granted.code_challenge):
            return _oauth_error("invalid_grant", "PKCE verification failed")
        try:
            require_workspace_identity(
                {
                    "email": granted.email,
                    "email_verified": True,
                    "hd": granted.hosted_domain,
                },
                settings.google_hosted_domain,
            )
        except IdentityRejected:
            return _oauth_error("invalid_grant", "account is outside the wrap2earn organization")
        return await _token_response(
            subject=granted.google_sub,
            email=granted.email,
            hosted_domain=granted.hosted_domain,
            client_id=granted.client_id,
        )

    async def _refresh_grant(form: dict[str, str], client_id: str) -> JSONResponse:
        raw_refresh = form.get("refresh_token", "")
        if not raw_refresh or not client_id:
            return _oauth_error("invalid_request", "refresh_token and client_id are required")
        replacement = secrets.token_urlsafe(32)
        try:
            grant = await store.rotate_refresh_token(
                raw_refresh,
                replacement,
                ttl_seconds=settings.oauth_refresh_token_ttl_seconds,
                client_id=client_id,
            )
        except RefreshReuse:
            logger.warning("refresh_token_reuse", extra={"client_id": client_id})
            return _oauth_error("invalid_grant", "refresh token was already used")
        if grant is None:
            return _oauth_error("invalid_grant", "refresh token is invalid")
        access = _access_token(
            subject=grant.google_sub,
            email=grant.email,
            hosted_domain=grant.hosted_domain,
            client_id=grant.client_id,
        )
        return _bearer_response(access, replacement)

    async def _token_response(
        *,
        subject: str,
        email: str,
        hosted_domain: str,
        client_id: str,
    ) -> JSONResponse:
        refresh = secrets.token_urlsafe(32)
        await store.save_refresh_token(
            refresh,
            client_id=client_id,
            google_sub=subject,
            email=email,
            hosted_domain=hosted_domain,
            ttl_seconds=settings.oauth_refresh_token_ttl_seconds,
        )
        access = _access_token(
            subject=subject,
            email=email,
            hosted_domain=hosted_domain,
            client_id=client_id,
        )
        return _bearer_response(access, refresh)

    def _access_token(*, subject: str, email: str, hosted_domain: str, client_id: str) -> str:
        return issue_access_token(
            secret=settings.oauth_jwt_secret,
            issuer=public,
            subject=subject,
            email=email,
            hosted_domain=hosted_domain,
            client_id=client_id,
            audiences=audiences,
            ttl_seconds=settings.oauth_access_token_ttl_seconds,
        )

    def _bearer_response(access: str, refresh: str) -> JSONResponse:
        return JSONResponse(
            content={
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": settings.oauth_access_token_ttl_seconds,
                "refresh_token": refresh,
                "scope": "mcp",
            },
            headers={"Cache-Control": "no-store"},
        )


def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": error, "error_description": description},
        headers={"Cache-Control": "no-store"},
    )


def _page(status: int, message: str) -> HTMLResponse:
    safe = html.escape(message)
    return HTMLResponse(
        "<!doctype html><html><head><title>Sign-in failed</title></head>"
        f"<body><h1>Sign-in failed</h1><p>{safe}</p></body></html>",
        status_code=status,
    )


def _redirect_error(redirect_uri: str, error: str, description: str, state: str) -> RedirectResponse:
    params = {"error": error, "error_description": description}
    if state:
        params["state"] = state
    return RedirectResponse(_with_query(redirect_uri, params), status_code=302)


def _with_query(uri: str, params: dict[str, str]) -> str:
    parts = urlsplit(uri)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


async def _form(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        if not isinstance(body, dict):
            return {}
        return {str(key): str(value) for key, value in body.items()}
    raw = (await request.body()).decode()
    return {key: value for key, value in parse_qsl(raw)}
