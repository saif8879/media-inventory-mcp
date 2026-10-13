from __future__ import annotations

import base64
import hashlib


def pkce_s256_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def pkce_s256_valid(verifier: str, challenge: str) -> bool:
    if not verifier or not challenge:
        return False
    expected = pkce_s256_challenge(verifier)
    if len(expected) != len(challenge):
        return False
    result = 0
    for left, right in zip(expected.encode("ascii"), challenge.encode("ascii"), strict=True):
        result |= left ^ right
    return result == 0
