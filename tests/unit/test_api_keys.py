import json

import pytest

from backend.security.api_keys import DefaultApiKeyAuthenticator
from backend.security.contract import ApiKeyAuthenticator, AuthenticationError, Principal, Scope
from tests.helpers import NO_SCOPE_KEY, READER_KEY, TEST_API_KEYS_JSON, sha256_hex


def _authenticator(api_keys_json: str = TEST_API_KEYS_JSON) -> ApiKeyAuthenticator:
    return DefaultApiKeyAuthenticator(api_keys_json)


def test_reader_key_resolves_to_reviewer() -> None:
    assert _authenticator().authenticate(READER_KEY) == Principal(
        name="reviewer", scopes=frozenset({Scope.TRANSACTIONS_READ})
    )


def test_no_scope_key_resolves_to_principal_without_scopes() -> None:
    principal = _authenticator().authenticate(NO_SCOPE_KEY)

    assert principal.name == "no-scope"
    assert principal.scopes == frozenset()


@pytest.mark.parametrize("api_key", ["unknown-key", "", None])
def test_unknown_or_missing_key_is_rejected(api_key: str | None) -> None:
    with pytest.raises(AuthenticationError, match="invalid or missing API key"):
        _authenticator().authenticate(api_key)


def test_hash_of_key_is_not_accepted_as_key() -> None:
    with pytest.raises(AuthenticationError):
        _authenticator().authenticate(sha256_hex(READER_KEY))


@pytest.mark.parametrize(
    "api_keys_json",
    [
        "not json",
        json.dumps([sha256_hex(READER_KEY)]),
        json.dumps({sha256_hex(READER_KEY): {"name": "reviewer", "scopes": ["transactions:admin"]}}),
    ],
)
def test_malformed_config_fails_closed(api_keys_json: str) -> None:
    authenticator = _authenticator(api_keys_json)

    for key in (READER_KEY, NO_SCOPE_KEY, ""):
        with pytest.raises(AuthenticationError):
            authenticator.authenticate(key)
