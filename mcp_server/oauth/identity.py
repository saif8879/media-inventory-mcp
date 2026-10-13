from __future__ import annotations


class IdentityRejected(Exception):
    """Google account is not a verified member of the allowed Workspace domain."""


def require_workspace_identity(claims: dict, hosted_domain: str) -> None:
    """Accept only a verified account whose hosted domain and email match."""
    domain = hosted_domain.strip().lower()
    email = str(claims.get("email") or "").strip().lower()
    hosted = str(claims.get("hd") or "").strip().lower()
    verified = claims.get("email_verified")
    if verified is not True and verified != "true":
        raise IdentityRejected("Google email is not verified")
    if hosted != domain:
        raise IdentityRejected(
            f"Google account is outside the {domain} organization"
        )
    if not email.endswith(f"@{domain}"):
        raise IdentityRejected("Google email domain is not allowed")
