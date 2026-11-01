from typing import Protocol

from backend.domain.models import IngestOutcome, TransactionWebhook


class WebhookIngestionService(Protocol):
    async def accept(self, event: TransactionWebhook) -> IngestOutcome:
        """Persist the webhook, then enqueue it for processing.

        Never acknowledges an event it failed to persist.
        Raises PersistenceError or EnqueueError; the route maps both to 503 so the sender retries.
        """
        ...
