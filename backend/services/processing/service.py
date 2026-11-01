from backend.database.repositories.transaction_repository import TransactionRepository
from backend.domain.errors import SettlementError, SettlementRetry
from backend.domain.models import ProcessOutcome, TransactionStatus
from backend.integrations.settlement.contract import SettlementGateway

BASE_RETRY_DELAY_SECONDS = 5
MAX_RETRY_DELAY_SECONDS = 60


def retry_delay_seconds(attempt: int) -> int:
    """Exponential backoff: attempt 1 -> 5s, 2 -> 10s, 3 -> 20s, capped at 60s."""
    return min(MAX_RETRY_DELAY_SECONDS, BASE_RETRY_DELAY_SECONDS << max(attempt - 1, 0))


class DefaultTransactionProcessor:
    """Settles a transaction once and marks it PROCESSED."""

    def __init__(self, repository: TransactionRepository, gateway: SettlementGateway) -> None:
        self._repository = repository
        self._gateway = gateway

    async def process(self, transaction_id: str) -> ProcessOutcome:
        txn = await self._repository.record_attempt(transaction_id)
        if txn is None:
            return ProcessOutcome.NOT_FOUND
        if txn.status is TransactionStatus.PROCESSED:
            return ProcessOutcome.ALREADY_PROCESSED
        try:
            await self._gateway.settle(txn)
        except SettlementError as err:
            await self._repository.record_failure(transaction_id, str(err))
            raise SettlementRetry(retry_delay_seconds(txn.attempts), str(err)) from err
        marked = await self._repository.mark_processed(transaction_id)
        return ProcessOutcome.PROCESSED if marked else ProcessOutcome.ALREADY_PROCESSED
