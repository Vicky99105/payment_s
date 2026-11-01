"""In-memory implementations of the infrastructure contracts. Tests use these, never mocks."""

from dataclasses import replace
from datetime import UTC, datetime

from backend.domain.errors import EnqueueError, PersistenceError, SettlementError
from backend.domain.models import Transaction, TransactionStatus, TransactionWebhook


def _now() -> datetime:
    return datetime.now(UTC)


class FakeTransactionRepository:
    def __init__(self) -> None:
        self.rows: dict[str, Transaction] = {}
        self.deliveries: list[TransactionWebhook] = []
        self.fail_next_ingest = False

    async def ingest(self, event: TransactionWebhook) -> tuple[Transaction, bool]:
        if self.fail_next_ingest:
            self.fail_next_ingest = False
            raise PersistenceError("simulated database failure")
        self.deliveries.append(event)
        if event.transaction_id in self.rows:
            return self.rows[event.transaction_id], False
        now = _now()
        txn = Transaction(
            transaction_id=event.transaction_id,
            source_account=event.source_account,
            destination_account=event.destination_account,
            amount=event.amount,
            currency=event.currency,
            status=TransactionStatus.PROCESSING,
            attempts=0,
            last_error=None,
            created_at=now,
            updated_at=now,
            processed_at=None,
        )
        self.rows[event.transaction_id] = txn
        return txn, True

    async def get(self, transaction_id: str) -> Transaction | None:
        return self.rows.get(transaction_id)

    async def record_attempt(self, transaction_id: str) -> Transaction | None:
        txn = self.rows.get(transaction_id)
        if txn is None:
            return None
        if txn.status is TransactionStatus.PROCESSING:
            txn = replace(txn, attempts=txn.attempts + 1, updated_at=_now())
            self.rows[transaction_id] = txn
        return txn

    async def record_failure(self, transaction_id: str, error: str) -> None:
        txn = self.rows.get(transaction_id)
        if txn is not None:
            self.rows[transaction_id] = replace(txn, last_error=error, updated_at=_now())

    async def mark_processed(self, transaction_id: str) -> bool:
        txn = self.rows.get(transaction_id)
        if txn is None or txn.status is TransactionStatus.PROCESSED:
            return False
        now = _now()
        self.rows[transaction_id] = replace(
            txn, status=TransactionStatus.PROCESSED, processed_at=now, updated_at=now
        )
        return True

    def seed_processed(self, event: TransactionWebhook) -> None:
        """Test helper: put an already-PROCESSED row in place."""
        now = _now()
        self.rows[event.transaction_id] = Transaction(
            transaction_id=event.transaction_id,
            source_account=event.source_account,
            destination_account=event.destination_account,
            amount=event.amount,
            currency=event.currency,
            status=TransactionStatus.PROCESSED,
            attempts=1,
            last_error=None,
            created_at=now,
            updated_at=now,
            processed_at=now,
        )


class FakeTaskQueue:
    """Mirrors Vercel Queues: a repeated idempotency key is silently dropped."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delivered: list[str] = []
        self.failures_remaining = 0

    async def enqueue(self, transaction_id: str) -> None:
        self.calls.append(transaction_id)
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise EnqueueError("simulated queue outage")
        if transaction_id not in self.delivered:
            self.delivered.append(transaction_id)


class FakeSettlementGateway:
    def __init__(self) -> None:
        self.settled: list[str] = []
        self.failures_remaining = 0

    async def settle(self, transaction: Transaction) -> None:
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise SettlementError("simulated settlement failure")
        self.settled.append(transaction.transaction_id)
