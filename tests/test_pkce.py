from mcp_server.oauth.pkce import pkce_s256_challenge, pkce_s256_valid


def test_s256_challenge_matches_verifier() -> None:
    verifier = "a" * 43
    challenge = pkce_s256_challenge(verifier)
    assert pkce_s256_valid(verifier, challenge)


def test_s256_rejects_wrong_verifier() -> None:
    challenge = pkce_s256_challenge("correct-verifier-value")
    assert pkce_s256_valid("other-verifier-value", challenge) is False
