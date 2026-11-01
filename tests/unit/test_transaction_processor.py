import pytest

from backend.domain.errors import SettlementRetry
from backend.domain.models import ProcessOutcome, TransactionStatus
from backend.services.processing.contract import TransactionProcessor
from backend.services.processing.service import DefaultTransactionProcessor
from tests.fakes import FakeSettlementGateway, FakeTransactionRepository
from tests.helpers import make_event

TXN_ID = "txn_abc123def456"


async def _build() -> tuple[TransactionProcessor, FakeTransactionRepository, FakeSettlementGateway]:
    repo = FakeTransactionRepository()
    gateway = FakeSettlementGateway()
    await repo.ingest(make_event(TXN_ID))
    return DefaultTransactionProcessor(repo, gateway), repo, gateway


async def test_process_settles_and_marks_processed() -> None:
    processor, repo, gateway = await _build()

    outcome = await processor.process(TXN_ID)

    assert outcome is ProcessOutcome.PROCESSED
    assert gateway.settled == [TXN_ID]
    row = repo.rows[TXN_ID]
    assert row.status is TransactionStatus.PROCESSED
    assert row.processed_at is not None
    assert row.attempts == 1


async def test_second_process_is_a_no_op() -> None:
    processor, repo, gateway = await _build()
    await processor.process(TXN_ID)
    first_processed_at = repo.rows[TXN_ID].processed_at

    outcome = await processor.process(TXN_ID)

    assert outcome is ProcessOutcome.ALREADY_PROCESSED
    assert gateway.settled == [TXN_ID]
    assert repo.rows[TXN_ID].processed_at == first_processed_at


async def test_settlement_failure_backs_off_then_succeeds() -> None:
    processor, repo, gateway = await _build()
    gateway.failures_remaining = 2

    with pytest.raises(SettlementRetry) as first:
        await processor.process(TXN_ID)
    assert first.value.delay_seconds == 5
    row = repo.rows[TXN_ID]
    assert row.last_error is not None
    assert row.attempts == 1
    assert row.status is TransactionStatus.PROCESSING

    with pytest.raises(SettlementRetry) as second:
        await processor.process(TXN_ID)
    assert second.value.delay_seconds == 10

    outcome = await processor.process(TXN_ID)

    assert outcome is ProcessOutcome.PROCESSED
    assert repo.rows[TXN_ID].attempts == 3


async def test_unknown_transaction_is_not_found() -> None:
    processor, _, gateway = await _build()

    outcome = await processor.process("txn_unknown")

    assert outcome is ProcessOutcome.NOT_FOUND
    assert gateway.settled == []
