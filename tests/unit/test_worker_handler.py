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
