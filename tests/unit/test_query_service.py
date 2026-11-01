from backend.services.query.contract import TransactionQueryService
from backend.services.query.service import DefaultTransactionQueryService
from tests.fakes import FakeTransactionRepository
from tests.helpers import make_event


async def test_get_returns_known_transaction_and_none_for_unknown() -> None:
    repo = FakeTransactionRepository()
    txn, _ = await repo.ingest(make_event("txn_known"))
    service: TransactionQueryService = DefaultTransactionQueryService(repo)

    assert await service.get("txn_known") == txn
    assert await service.get("txn_unknown") is None
