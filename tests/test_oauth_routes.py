from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from mcp_server.oauth.google import GoogleVerificationError
from mcp_server.oauth.pkce import pkce_s256_challenge
from mcp_server.server import create_app

PUBLIC = "https://mcp.wrap2earn.test"
REDIRECT = "http://127.0.0.1:8765/callback"


class FakeGoogle:
    def __init__(self) -> None:
        self.claims = {
            "sub": "google-subject",
            "email": "person@wrap2earn.com",
            "email_verified": True,
            "hd": "wrap2earn.com",
        }
        self.nonce: str | None = None

    def authorization_url(self, *, state: str, nonce: str) -> str:
        self.nonce = nonce
        return f"https://accounts.google.com/o/oauth2/v2/auth?state={state}"

    async def exchange(self, code: str) -> dict:
        if code == "bad":
            raise GoogleVerificationError("google token rejected")
        return {**self.claims, "nonce": self.nonce}


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def client(google: FakeGoogle) -> TestClient:
    app = create_app(oauth_database_url="sqlite+aiosqlite://", google=google)

    @app.get("/api/test-auth-verify")
    def verify_auth():
        return {"authorized": True}

    with TestClient(app) as test_client:
        yield test_client


def test_health_stays_open(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    response = client.get("/mcp")
    assert response.status_code == 401
    header = response.headers["www-authenticate"]
    assert f'{PUBLIC}/.well-known/oauth-protected-resource' in header


def test_legacy_shared_api_key_is_rejected(client: TestClient) -> None:
    response = client.get("/mcp", headers={"Authorization": "Bearer legacy-shared-key"})
    assert response.status_code == 401


def test_authorization_server_metadata_advertises_pkce_and_registration(client: TestClient) -> None:
    response = client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    body = response.json()
    assert body["issuer"] == PUBLIC
    assert body["authorization_endpoint"] == f"{PUBLIC}/authorize"
    assert body["token_endpoint"] == f"{PUBLIC}/token"
    assert body["registration_endpoint"] == f"{PUBLIC}/register"
    assert "S256" in body["code_challenge_methods_supported"]


def test_protected_resource_metadata_names_this_server(client: TestClient) -> None:
    response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == f"{PUBLIC}/mcp"
    assert body["authorization_servers"] == [PUBLIC]


def test_wrap2earn_login_issues_a_bearer_token(client: TestClient) -> None:
    verifier = "a" * 43
    access_token, _refresh_token = _login(client, verifier)
    response = client.get(
        "/api/test-auth-verify",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"authorized": True}


def test_gmail_account_gets_no_authorization_code(client: TestClient, google: FakeGoogle) -> None:
    google.claims = {
        "sub": "other",
        "email": "person@gmail.com",
        "email_verified": True,
        "hd": "gmail.com",
    }
    registered = _register(client)
    authorize = _authorize(client, registered["client_id"], "b" * 43)
    state = parse_qs(urlsplit(authorize.headers["location"]).query)["state"][0]
    callback = client.get(
        "/auth/google/callback",
        params={"code": "good", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 403
    assert "wrap2earn" in callback.text
    assert "location" not in callback.headers


def test_reused_authorization_code_is_rejected(client: TestClient) -> None:
    verifier = "c" * 43
    _access, _refresh, code, client_id = _login_with_code(client, verifier)
    again = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert again.status_code == 400
    assert again.json()["error"] == "invalid_grant"


def test_wrong_pkce_verifier_is_rejected(client: TestClient) -> None:
    registered = _register(client)
    authorize = _authorize(client, registered["client_id"], "e" * 43)
    state = parse_qs(urlsplit(authorize.headers["location"]).query)["state"][0]
    callback = client.get(
        "/auth/google/callback",
        params={"code": "good", "state": state},
        follow_redirects=False,
    )
    auth_code = parse_qs(urlsplit(callback.headers["location"]).query)["code"][0]
    rejected = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT,
            "client_id": registered["client_id"],
            "code_verifier": "not-the-verifier",
        },
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"] == "invalid_grant"


def test_refresh_token_rotates_and_reuse_is_rejected(client: TestClient) -> None:
    _access, refresh, _code, client_id = _login_with_code(client, "f" * 43)
    refreshed = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
        },
    )
    assert refreshed.status_code == 200
    new_refresh = refreshed.json()["refresh_token"]
    assert new_refresh != refresh
    reused = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
        },
    )
    assert reused.status_code == 400
    assert reused.json()["error"] == "invalid_grant"
    sibling = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": new_refresh,
            "client_id": client_id,
        },
    )
    assert sibling.status_code == 400
    assert sibling.json()["error"] == "invalid_grant"


def test_register_rejects_public_http_redirect(client: TestClient) -> None:
    response = client.post(
        "/register",
        json={"redirect_uris": ["http://evil.example/callback"]},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def _register(client: TestClient) -> dict:
    response = client.post(
        "/register",
        json={
            "client_name": "Cursor",
            "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert response.status_code == 201
    return response.json()


def _authorize(client: TestClient, client_id: str, verifier: str):
    return client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": pkce_s256_challenge(verifier),
            "code_challenge_method": "S256",
            "state": "client-state",
            "scope": "mcp",
            "resource": f"{PUBLIC}/mcp",
        },
        follow_redirects=False,
    )


def _login(client: TestClient, verifier: str) -> tuple[str, str]:
    access, refresh, _code, _client_id = _login_with_code(client, verifier)
    return access, refresh


def _login_with_code(client: TestClient, verifier: str) -> tuple[str, str, str, str]:
    registered = _register(client)
    client_id = registered["client_id"]
    authorize = _authorize(client, client_id, verifier)
    assert authorize.status_code == 302
    state = parse_qs(urlsplit(authorize.headers["location"]).query)["state"][0]
    callback = client.get(
        "/auth/google/callback",
        params={"code": "good", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 302
    query = parse_qs(urlsplit(callback.headers["location"]).query)
    assert query["state"] == ["client-state"]
    code = query["code"][0]
    token = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200
    body = token.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    return body["access_token"], body["refresh_token"], code, client_id
