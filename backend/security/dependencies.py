"""FastAPI dependency factories bound to security contracts. Errors propagate to the app's exception handlers."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request

from backend.security.contract import (
    ApiKeyAuthenticator,
    AuthenticationError,
    AuthorizationError,
    Principal,
    Scope,
    WebhookSignatureVerifier,
)

PrincipalDependency = Callable[..., Awaitable[Principal]]


def webhook_principal_dependency(verifier: WebhookSignatureVerifier) -> PrincipalDependency:
    """Authenticate a webhook by its signature over the raw request body."""

    async def dependency(request: Request) -> Principal:
        return verifier.verify(
            await request.body(),
            request.headers.get("X-Webhook-Timestamp"),
            request.headers.get("X-Webhook-Signature"),
        )

    return dependency


def bearer_principal_dependency(authenticator: ApiKeyAuthenticator) -> PrincipalDependency:
    """Authenticate `Authorization: Bearer <key>`; any other scheme is unauthenticated."""

    async def dependency(request: Request) -> Principal:
        scheme, _, key = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not key.strip():
            raise AuthenticationError("invalid or missing API key")
        return authenticator.authenticate(key.strip())

    return dependency


def require_scope(scope: Scope, principal_dependency: PrincipalDependency) -> PrincipalDependency:
    """Wrap a principal dependency so it also requires `scope`."""

    async def dependency(principal: Annotated[Principal, Depends(principal_dependency)]) -> Principal:
        if not principal.has(scope):
            raise AuthorizationError(f"missing scope {scope.value}")
        return principal

    return dependency
