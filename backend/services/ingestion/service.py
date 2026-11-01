from backend.database.repositories.transaction_repository import TransactionRepository
from backend.domain.models import IngestOutcome, TransactionStatus, TransactionWebhook
from backend.integrations.queue.contract import TaskQueue


class DefaultWebhookIngestionService:
    """Persist-then-enqueue ingestion of payment webhooks."""

    def __init__(self, repository: TransactionRepository, queue: TaskQueue) -> None:
        self._repository = repository
        self._queue = queue

    async def accept(self, event: TransactionWebhook) -> IngestOutcome:
        txn, created = await self._repository.ingest(event)
        if txn.status is TransactionStatus.PROCESSED:
            return IngestOutcome.DUPLICATE_COMPLETED
        await self._queue.enqueue(event.transaction_id)
        return IngestOutcome.CREATED if created else IngestOutcome.DUPLICATE_IN_FLIGHT
