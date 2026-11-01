from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from backend.api.schemas import TransactionWebhookIn, WebhookAck
from backend.security.contract import Principal, Scope, WebhookSignatureVerifier
from backend.security.dependencies import require_scope, webhook_principal_dependency
from backend.services.ingestion.contract import WebhookIngestionService


def build_router(ingestion: WebhookIngestionService, verifier: WebhookSignatureVerifier) -> APIRouter:
    router = APIRouter()
    authorized = require_scope(Scope.WEBHOOKS_WRITE, webhook_principal_dependency(verifier))

    @router.post("/v1/webhooks/transactions", status_code=status.HTTP_202_ACCEPTED, response_model=WebhookAck)
    async def receive_transaction(request: Request, _: Annotated[Principal, Depends(authorized)]) -> WebhookAck:
        # Authenticate first, parse second: unsigned callers learn nothing about the payload rules.
        try:
            payload = TransactionWebhookIn.model_validate_json(await request.body())
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from None
        await ingestion.accept(payload.to_domain())
        return WebhookAck(transaction_id=payload.transaction_id)

    return router
