from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from backend.api.schemas import TransactionOut
from backend.security.contract import ApiKeyAuthenticator, Principal, Scope
from backend.security.dependencies import bearer_principal_dependency, require_scope
from backend.services.query.contract import TransactionQueryService


def build_router(query: TransactionQueryService, authenticator: ApiKeyAuthenticator) -> APIRouter:
    router = APIRouter()
    authorized = require_scope(Scope.TRANSACTIONS_READ, bearer_principal_dependency(authenticator))

    @router.get("/v1/transactions/{transaction_id}", response_model=list[TransactionOut])
    async def get_transaction(
        transaction_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_\-]{1,64}$")],
        _: Annotated[Principal, Depends(authorized)],
    ) -> list[TransactionOut]:
        txn = await query.get(transaction_id)
        if txn is None:
            raise HTTPException(status_code=404, detail="transaction not found")
        return [TransactionOut.from_domain(txn)]

    return router
