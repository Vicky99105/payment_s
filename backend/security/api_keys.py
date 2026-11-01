"""Bearer API key authentication against a config table of sha256 key hashes."""

import hashlib
import json
import logging

from backend.security.contract import AuthenticationError, Principal, Scope

logger = logging.getLogger(__name__)


def _parse(api_keys_json: str) -> dict[str, Principal]:
    """Raises ValueError (or a subclass) on any malformed shape or unknown scope."""
    raw = json.loads(api_keys_json)
    if not isinstance(raw, dict):
        raise ValueError("API_KEYS must be a JSON object")
    table: dict[str, Principal] = {}
    for key_hash, entry in raw.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ValueError("API_KEYS entry must have a string name")
        scopes = entry.get("scopes")
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            raise ValueError("API_KEYS entry scopes must be a list of strings")
        table[key_hash.lower()] = Principal(name=entry["name"], scopes=frozenset(Scope(s) for s in scopes))
    return table


class DefaultApiKeyAuthenticator:
    """Resolves a presented key by its sha256 hex. A malformed key table fails closed as an empty table."""

    def __init__(self, api_keys_json: str) -> None:
        try:
            self._principals = _parse(api_keys_json)
        except ValueError:
            logger.warning("API_KEYS is malformed; API key authentication is disabled")
            self._principals = {}

    def authenticate(self, api_key: str | None) -> Principal:
        principal = self._principals.get(hashlib.sha256(api_key.encode()).hexdigest()) if api_key else None
        if principal is None:
            raise AuthenticationError("invalid or missing API key")
        return principal
