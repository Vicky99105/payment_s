import pytest
from vercel.queue import RetryAfter

from backend.domain.errors import SettlementRetry
from backend.domain.models import ProcessOutcome
from backend.worker.handler import handle_transaction_message

TXN_ID = "txn_abc123def456"


class StubProcessor:
    """Returns a fixed outcome, or raises a fixed exception."""

    def __init__(self, outcome: ProcessOutcome = ProcessOutcome.PROCESSED, error: Exception | None = None) -> None:
        self._outcome = outcome
        self._error = error
        self.calls: list[str] = []

    async def process(self, transaction_id: str) -> ProcessOutcome:
        self.calls.append(transaction_id)
        if self._error is not None:
            raise self._error
        return self._outcome


async def test_success_returns_outcome() -> None:
    processor = StubProcessor()

    outcome = await handle_transaction_message(processor, TXN_ID)

    assert outcome is ProcessOutcome.PROCESSED
    assert processor.calls == [TXN_ID]


async def test_settlement_retry_becomes_queue_retry_after() -> None:
    processor = StubProcessor(error=SettlementRetry(5))

    with pytest.raises(RetryAfter) as raised:
        await handle_transaction_message(processor, TXN_ID)

    assert raised.value.timeout_seconds == 5


async def test_other_exceptions_propagate_unchanged() -> None:
    error = RuntimeError("boom")
    processor = StubProcessor(error=error)

    with pytest.raises(RuntimeError) as raised:
        await handle_transaction_message(processor, TXN_ID)

    assert raised.value is error


async def test_database_unavailable_becomes_short_queue_retry() -> None:
    """A transient DB outage (e.g. pooler connection cap) retries in seconds, not after the 5-minute lease."""
    from backend.domain.errors import PersistenceError
    from backend.worker.handler import DB_RETRY_DELAY_SECONDS

    processor = StubProcessor(error=PersistenceError("pooler full"))
    with pytest.raises(RetryAfter) as exc_info:
        await handle_transaction_message(processor, "txn_db")
    assert exc_info.value.timeout_seconds == DB_RETRY_DELAY_SECONDS


def test_worker_concurrency_is_capped_within_the_connection_budget() -> None:
    """Workers and webhooks share the pooler's 200 client connections; workers must leave headroom."""
    from backend.config import Settings
    from backend.database.pool import MAX_SIZE

    assert Settings(_env_file=None).worker_max_concurrency * 1 <= 50  # type: ignore[call-arg]
    assert MAX_SIZE <= 2
