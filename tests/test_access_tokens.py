import pytest

from mcp_server.oauth.tokens import (
    TokenRejected,
    decode_access_token,
    issue_access_token,
    issue_state_token,
    read_state_token,
)

SECRET = "test-secret-with-at-least-32-bytes"
ISSUER = "https://mcp.wrap2earn.test"
AUDIENCES = ["https://mcp.wrap2earn.test/mcp", "https://mcp.wrap2earn.test/sse"]


def test_access_token_round_trip_keeps_workspace_claims() -> None:
    token = issue_access_token(
        secret=SECRET,
        issuer=ISSUER,
        subject="google-subject",
        email="person@wrap2earn.com",
        hosted_domain="wrap2earn.com",
        client_id="client-1",
        audiences=AUDIENCES,
        ttl_seconds=3600,
    )
    claims = decode_access_token(token, secret=SECRET, issuer=ISSUER, audiences=AUDIENCES)
    assert claims["sub"] == "google-subject"
    assert claims["email"] == "person@wrap2earn.com"
    assert claims["hd"] == "wrap2earn.com"
    assert claims["client_id"] == "client-1"


def test_access_token_rejects_expired_token() -> None:
    token = issue_access_token(
        secret=SECRET,
        issuer=ISSUER,
        subject="google-subject",
        email="person@wrap2earn.com",
        hosted_domain="wrap2earn.com",
        client_id="client-1",
        audiences=AUDIENCES,
        ttl_seconds=-10,
    )
    with pytest.raises(TokenRejected):
        decode_access_token(token, secret=SECRET, issuer=ISSUER, audiences=AUDIENCES)


def test_state_token_round_trip() -> None:
    payload = {"client_id": "client-1", "nonce": "n-1", "client_state": "abc"}
    token = issue_state_token(payload, secret=SECRET, ttl_seconds=600)
    assert read_state_token(token, secret=SECRET)["nonce"] == "n-1"
