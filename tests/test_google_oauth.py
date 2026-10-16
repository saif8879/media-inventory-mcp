from urllib.parse import parse_qs, urlsplit

from mcp_server.oauth.google import GoogleOAuth


def test_authorization_url_limits_login_to_wrap2earn_domain() -> None:
    google = GoogleOAuth(
        client_id="test-google-client",
        client_secret="test-google-secret",
        redirect_uri="https://mcp.wrap2earn.test/auth/google/callback",
        hosted_domain="wrap2earn.com",
    )
    url = google.authorization_url(state="signed-state", nonce="nonce-1")
    query = parse_qs(urlsplit(url).query)
    assert query["hd"] == ["wrap2earn.com"]
    assert query["nonce"] == ["nonce-1"]
    assert query["state"] == ["signed-state"]
    assert query["redirect_uri"] == ["https://mcp.wrap2earn.test/auth/google/callback"]
    assert "openid" in query["scope"][0]
