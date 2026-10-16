from mcp_server.oauth.identity import IdentityRejected, require_workspace_identity


def _claims(**overrides: object) -> dict:
    claims = {
        "email": "person@wrap2earn.com",
        "email_verified": True,
        "hd": "wrap2earn.com",
        "sub": "google-subject",
    }
    claims.update(overrides)
    return claims


def test_accepts_verified_wrap2earn_workspace_account() -> None:
    require_workspace_identity(_claims(), "wrap2earn.com")


def test_rejects_account_outside_wrap2earn() -> None:
    try:
        require_workspace_identity(
            _claims(email="person@gmail.com", hd="gmail.com"),
            "wrap2earn.com",
        )
    except IdentityRejected as exc:
        assert "wrap2earn" in str(exc)
    else:
        raise AssertionError("expected IdentityRejected")


def test_rejects_unverified_email_even_on_wrap2earn_domain() -> None:
    try:
        require_workspace_identity(_claims(email_verified=False), "wrap2earn.com")
    except IdentityRejected as exc:
        assert "verified" in str(exc)
    else:
        raise AssertionError("expected IdentityRejected")


def test_rejects_email_whose_domain_does_not_match_hosted_domain() -> None:
    try:
        require_workspace_identity(
            _claims(email="person@other.com"),
            "wrap2earn.com",
        )
    except IdentityRejected as exc:
        assert "domain" in str(exc)
    else:
        raise AssertionError("expected IdentityRejected")
