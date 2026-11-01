import asyncio
from decimal import Decimal

import asyncpg
import pytest

from backend.database.pool import LazyPool
from backend.database.repositories.transaction_repository import DefaultTransactionRepository
from backend.domain.errors import PersistenceError
from backend.domain.models import TransactionStatus, TransactionWebhook
from tests.integration.conftest import new_id


def _repo(pool: asyncpg.Pool) -> DefaultTransactionRepository:
    async def provider() -> asyncpg.Pool:
        return pool

    return DefaultTransactionRepository(provider)


def _event(transaction_id: str) -> TransactionWebhook:
    return TransactionWebhook(
        transaction_id=transaction_id,
        source_account="acc_user_789",
        destination_account="acc_merchant_456",
        amount=Decimal("150.50"),
        currency="USD",
    )


async def _delivery_count(pool: asyncpg.Pool, transaction_id: str) -> int:
    count = await pool.fetchval(
        "SELECT count(*) FROM webhook_deliveries WHERE transaction_id = $1", transaction_id
    )
    assert isinstance(count, int)
    return count


async def test_ingest_creates_once_and_logs_every_delivery(pool: asyncpg.Pool) -> None:
    repo = _repo(pool)
    tid = new_id()

    first, created = await repo.ingest(_event(tid))
    assert created is True
    assert first.status is TransactionStatus.PROCESSING
    assert await _delivery_count(pool, tid) == 1

    second, created_again = await repo.ingest(_event(tid))
    assert created_again is False
    assert second.created_at == first.created_at
    assert await _delivery_count(pool, tid) == 2


async def test_ingest_stores_amount_as_exact_string_in_payload(pool: asyncpg.Pool) -> None:
    repo = _repo(pool)
    tid = new_id()
    await repo.ingest(_event(tid))
    amount = await pool.fetchval(
        "SELECT payload->>'amount' FROM webhook_deliveries WHERE transaction_id = $1", tid
    )
    assert amount == "150.50"


async def test_get_round_trips_every_field(pool: asyncpg.Pool) -> None:
    repo = _repo(pool)
    tid = new_id()
    ingested, _ = await repo.ingest(_event(tid))

    txn = await repo.get(tid)
    assert txn == ingested
    assert txn is not None
    assert txn.transaction_id == tid
    assert txn.source_account == "acc_user_789"
    assert txn.destination_account == "acc_merchant_456"
    assert txn.amount == Decimal("150.50")
    assert str(txn.amount) == "150.50"
    assert txn.currency == "USD"
    assert txn.status is TransactionStatus.PROCESSING
    assert txn.attempts == 0
    assert txn.last_error is None
    assert txn.created_at.tzinfo is not None
    assert txn.updated_at >= txn.created_at
    assert txn.processed_at is None


async def test_get_unknown_returns_none(pool: asyncpg.Pool) -> None:
    assert await _repo(pool).get(new_id()) is None


async def test_record_attempt_increments_while_processing(pool: asyncpg.Pool) -> None:
    repo = _repo(pool)
    tid = new_id()
    await repo.ingest(_event(tid))

    one = await repo.record_attempt(tid)
    two = await repo.record_attempt(tid)
    assert one is not None and one.attempts == 1
    assert two is not None and two.attempts == 2


async def test_record_attempt_on_processed_row_does_not_increment(pool: asyncpg.Pool) -> None:
    repo = _repo(pool)
    tid = new_id()
    await repo.ingest(_event(tid))
    await repo.record_attempt(tid)
    assert await repo.mark_processed(tid) is True

    txn = await repo.record_attempt(tid)
    assert txn is not None
    assert txn.attempts == 1
    assert txn.status is TransactionStatus.PROCESSED


async def test_record_attempt_unknown_returns_none(pool: asyncpg.Pool) -> None:
    assert await _repo(pool).record_attempt(new_id()) is None


async def test_record_failure_sets_last_error_truncated(pool: asyncpg.Pool) -> None:
    repo = _repo(pool)
    tid = new_id()
    await repo.ingest(_event(tid))

    await repo.record_failure(tid, "settlement timed out")
    txn = await repo.get(tid)
    assert txn is not None and txn.last_error == "settlement timed out"

    await repo.record_failure(tid, "x" * 900)
    txn = await repo.get(tid)
    assert txn is not None and txn.last_error == "x" * 500


async def test_mark_processed_transitions_exactly_once(pool: asyncpg.Pool) -> None:
    repo = _repo(pool)
    tid = new_id()
    await repo.ingest(_event(tid))

    assert await repo.mark_processed(tid) is True
    assert await repo.mark_processed(tid) is False
    txn = await repo.get(tid)
    assert txn is not None
    assert txn.status is TransactionStatus.PROCESSED
    assert txn.processed_at is not None


async def test_mark_processed_unknown_returns_false(pool: asyncpg.Pool) -> None:
    assert await _repo(pool).mark_processed(new_id()) is False


async def test_concurrent_ingest_creates_exactly_one_row(pool: asyncpg.Pool) -> None:
    repo = _repo(pool)
    tid = new_id()

    results = await asyncio.gather(*(repo.ingest(_event(tid)) for _ in range(20)))

    assert sum(1 for _, created in results if created) == 1
    assert len({txn.created_at for txn, _ in results}) == 1
    rows = await pool.fetchval("SELECT count(*) FROM transactions WHERE transaction_id = $1", tid)
    assert rows == 1
    assert await _delivery_count(pool, tid) == 20


async def test_unreachable_database_raises_persistence_error() -> None:
    lazy = LazyPool("postgresql://u:p@127.0.0.1:1/db")
    repo = DefaultTransactionRepository(lazy.get)
    with pytest.raises(PersistenceError):
        await repo.get(new_id())
    with pytest.raises(PersistenceError):
        await repo.ingest(_event(new_id()))
    await lazy.close()


async def test_lazy_pool_creates_one_pool_and_reuses_it() -> None:
    from tests.integration.conftest import DATABASE_URL

    lazy = LazyPool(DATABASE_URL)
    try:
        pools = await asyncio.gather(*(lazy.get() for _ in range(5)))
        assert len({id(p) for p in pools}) == 1
        repo = DefaultTransactionRepository(lazy.get)
        assert await repo.get(new_id()) is None
    finally:
        await lazy.close()
