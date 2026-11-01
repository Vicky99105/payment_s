"""Authentication and authorization contracts. Single tenant: principals come from config, not a users table."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Scope(StrEnum):
    WEBHOOKS_WRITE = "webhooks:write"
    TRANSACTIONS_READ = "transactions:read"


@dataclass(frozen=True)
class Principal:
    name: str
    scopes: frozenset[Scope]

    def has(self, scope: Scope) -> bool:
        return scope in self.scopes


class AuthenticationError(Exception):
    """Caller identity could not be established. Maps to 401. The message is safe to return."""


class AuthorizationError(Exception):
    """Caller is known but lacks the required scope. Maps to 403."""


class WebhookSignatureVerifier(Protocol):
    def verify(self, raw_body: bytes, timestamp: str | None, signature: str | None) -> Principal:
        """Check `X-Webhook-Timestamp` / `X-Webhook-Signature` against the raw body.

        Signature format: "sha256=<hex>" of HMAC-SHA256(secret, f"{timestamp}.{raw_body}").
        Raises AuthenticationError if missing, malformed, stale (outside tolerance), or wrong.
        """
        ...


class ApiKeyAuthenticator(Protocol):
    def authenticate(self, api_key: str | None) -> Principal:
        """Resolve a bearer API key to its Principal. Raises AuthenticationError if missing or unknown."""
        ...
