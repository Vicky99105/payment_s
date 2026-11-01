from backend.database.repositories.transaction_repository import TransactionRepository
from backend.domain.models import Transaction


class DefaultTransactionQueryService:
    """Read-only access to stored transactions."""

    def __init__(self, repository: TransactionRepository) -> None:
        self._repository = repository

    async def get(self, transaction_id: str) -> Transaction | None:
        return await self._repository.get(transaction_id)
