from app.account_store import (
    _hash_password,
    _hash_session_token,
    _verify_password,
)


def test_password_hash_is_salted_and_verifiable():
    first_hash = _hash_password("test-password")
    second_hash = _hash_password("test-password")

    assert first_hash != second_hash
    assert _verify_password("test-password", first_hash)
    assert not _verify_password("wrong-password", first_hash)


def test_session_token_is_stored_as_a_one_way_hash():
    token = "random-session-token"

    assert _hash_session_token(token) != token
    assert _hash_session_token(token) == _hash_session_token(token)
