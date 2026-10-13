from __future__ import annotations

from urllib.parse import urlsplit


_BLOCKED_SCHEMES = frozenset({"javascript", "data", "file", "vbscript", "blob"})
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


def redirect_uri_error(uri: str) -> str | None:
    """Return an error message when a client redirect URI is not allowed."""
    if not uri or any(char.isspace() for char in uri):
        return "redirect URI is empty"
    if "#" in uri:
        return "redirect URI must not contain a fragment"
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    if scheme in _BLOCKED_SCHEMES or not scheme:
        return "redirect URI scheme is not allowed"
    if scheme == "http" and parts.hostname not in _LOCAL_HOSTS:
        return "http redirect URIs are only allowed for localhost"
    if scheme == "https" and not parts.hostname:
        return "https redirect URI needs a host"
    if scheme not in {"http", "https"} and not (parts.netloc or parts.path):
        return "redirect URI is incomplete"
    return None
