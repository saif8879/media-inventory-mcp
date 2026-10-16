from mcp_server.oauth.redirects import redirect_uri_error


def test_allows_localhost_and_https_and_app_scheme() -> None:
    assert redirect_uri_error("http://127.0.0.1:54321/callback") is None
    assert redirect_uri_error("http://localhost:8080/callback") is None
    assert redirect_uri_error("https://mcp.wrap2earn.com/callback") is None
    assert redirect_uri_error("cursor://anysphere.cursor-mcp/oauth/callback") is None


def test_rejects_public_http_and_dangerous_schemes() -> None:
    assert redirect_uri_error("http://evil.example/callback") is not None
    assert redirect_uri_error("javascript:alert(1)") is not None
    assert redirect_uri_error("https://mcp.wrap2earn.com/callback#frag") is not None
