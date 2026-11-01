from typing import Protocol

from backend.domain.models import Transaction


class TransactionQueryService(Protocol):
    async def get(self, transaction_id: str) -> Transaction | None: ...
