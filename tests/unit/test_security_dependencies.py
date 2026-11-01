from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.security.api_keys import DefaultApiKeyAuthenticator
from backend.security.contract import AuthenticationError, AuthorizationError, Principal, Scope
from backend.security.dependencies import bearer_principal_dependency, require_scope, webhook_principal_dependency
from backend.security.webhook_signature import DefaultWebhookSignatureVerifier
from tests.helpers import NO_SCOPE_KEY, READER_KEY, TEST_API_KEYS_JSON, TEST_SIGNING_SECRET, sign

BODY = b'{"transaction_id":"txn_abc123def456"}'


def _client() -> TestClient:
    app = FastAPI()
    webhook = webhook_principal_dependency(DefaultWebhookSignatureVerifier(TEST_SIGNING_SECRET))
    reader = require_scope(
        Scope.TRANSACTIONS_READ, bearer_principal_dependency(DefaultApiKeyAuthenticator(TEST_API_KEYS_JSON))
    )

    @app.exception_handler(AuthenticationError)
    async def _unauthenticated(_: Request, exc: AuthenticationError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=401)

    @app.exception_handler(AuthorizationError)
    async def _forbidden(_: Request, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.post("/webhooks")
    async def _webhooks(principal: Annotated[Principal, Depends(webhook)]) -> dict[str, str]:
        return {"principal": principal.name}

    @app.get("/transactions")
    async def _transactions(principal: Annotated[Principal, Depends(reader)]) -> dict[str, str]:
        return {"principal": principal.name}

    return TestClient(app)


def test_signed_webhook_is_accepted() -> None:
    response = _client().post("/webhooks", content=BODY, headers=sign(BODY))

    assert response.status_code == 200
    assert response.json() == {"principal": "payment-processor"}


def test_unsigned_webhook_is_unauthenticated() -> None:
    assert _client().post("/webhooks", content=BODY).status_code == 401


def test_reader_key_on_read_route_is_accepted() -> None:
    response = _client().get("/transactions", headers={"Authorization": f"Bearer {READER_KEY}"})

    assert response.status_code == 200
    assert response.json() == {"principal": "reviewer"}


def test_lowercase_bearer_scheme_is_accepted() -> None:
    assert _client().get("/transactions", headers={"Authorization": f"bearer {READER_KEY}"}).status_code == 200


def test_key_without_scope_is_forbidden() -> None:
    assert _client().get("/transactions", headers={"Authorization": f"Bearer {NO_SCOPE_KEY}"}).status_code == 403


@pytest.mark.parametrize("headers", [{"Authorization": "Basic xyz"}, {"Authorization": "Bearer"}, {}])
def test_missing_or_non_bearer_credentials_are_unauthenticated(headers: dict[str, str]) -> None:
    assert _client().get("/transactions", headers=headers).status_code == 401
