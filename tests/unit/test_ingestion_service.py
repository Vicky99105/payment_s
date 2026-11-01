import pytest

from backend.domain.errors import EnqueueError, PersistenceError
from backend.domain.models import IngestOutcome, TransactionStatus
from backend.services.ingestion.contract import WebhookIngestionService
from backend.services.ingestion.service import DefaultWebhookIngestionService
from tests.fakes import FakeTaskQueue, FakeTransactionRepository
from tests.helpers import make_event


def _build() -> tuple[WebhookIngestionService, FakeTransactionRepository, FakeTaskQueue]:
    repo = FakeTransactionRepository()
    queue = FakeTaskQueue()
    return DefaultWebhookIngestionService(repo, queue), repo, queue


async def test_new_transaction_is_stored_and_enqueued() -> None:
    service, repo, queue = _build()
    event = make_event()

    outcome = await service.accept(event)

    assert outcome is IngestOutcome.CREATED
    assert repo.rows[event.transaction_id].status is TransactionStatus.PROCESSING
    assert queue.calls == [event.transaction_id]


async def test_duplicate_while_processing_is_re_enqueued_and_deduped_by_queue() -> None:
    service, _, queue = _build()
    event = make_event()
    await service.accept(event)

    outcome = await service.accept(event)

    assert outcome is IngestOutcome.DUPLICATE_IN_FLIGHT
    assert queue.calls == [event.transaction_id, event.transaction_id]
    assert queue.delivered == [event.transaction_id]


async def test_duplicate_after_processed_is_not_enqueued() -> None:
    service, repo, queue = _build()
    event = make_event()
    repo.seed_processed(event)

    outcome = await service.accept(event)

    assert outcome is IngestOutcome.DUPLICATE_COMPLETED
    assert queue.calls == []


async def test_queue_failure_raises_and_leaves_row_for_sender_retry() -> None:
    service, repo, queue = _build()
    event = make_event()
    queue.failures_remaining = 1

    with pytest.raises(EnqueueError):
        await service.accept(event)
    assert repo.rows[event.transaction_id].status is TransactionStatus.PROCESSING

    outcome = await service.accept(event)

    assert outcome is IngestOutcome.DUPLICATE_IN_FLIGHT
    assert queue.delivered == [event.transaction_id]


async def test_repository_failure_raises_and_enqueues_nothing() -> None:
    service, repo, queue = _build()
    repo.fail_next_ingest = True

    with pytest.raises(PersistenceError):
        await service.accept(make_event())

    assert queue.calls == []
