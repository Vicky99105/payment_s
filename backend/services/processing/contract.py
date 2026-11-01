from typing import Protocol

from backend.domain.models import ProcessOutcome


class TransactionProcessor(Protocol):
    async def process(self, transaction_id: str) -> ProcessOutcome:
        """Settle one transaction and mark it PROCESSED. Safe to call any number of times.

        Raises SettlementRetry(delay_seconds) when settlement failed and must be retried later.
        """
        ...
