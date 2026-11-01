import time
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.domain.errors import SettlementError
from backend.domain.models import Transaction, TransactionStatus
from backend.integrations.settlement.simulated import DefaultSettlementGateway


def _txn(transaction_id: str = "txn_abc", attempts: int = 1) -> Transaction:
    now = datetime.now(UTC)
    return Transaction(
        transaction_id=transaction_id,
        source_account="acc_a",
        destination_account="acc_b",
        amount=Decimal("10.00"),
        currency="USD",
        status=TransactionStatus.PROCESSING,
        attempts=attempts,
        last_error=None,
        created_at=now,
        updated_at=now,
        processed_at=None,
    )


async def test_settle_waits_for_the_configured_delay() -> None:
    gateway = DefaultSettlementGateway(delay_seconds=0.05)
    started = time.monotonic()
    await gateway.settle(_txn())
    assert time.monotonic() - started >= 0.05


async def test_fault_injection_fails_only_the_first_attempt_for_the_prefix() -> None:
    gateway = DefaultSettlementGateway(delay_seconds=0, fault_injection=True)
    txn = _txn("faultinject_abc", attempts=1)
    with pytest.raises(SettlementError, match="injected settlement fault"):
        await gateway.settle(txn)
    await gateway.settle(replace(txn, attempts=2))


async def test_fault_injection_disabled_never_fails() -> None:
    gateway = DefaultSettlementGateway(delay_seconds=0)
    await gateway.settle(_txn("faultinject_abc", attempts=1))


async def test_fault_injection_ignores_other_ids() -> None:
    gateway = DefaultSettlementGateway(delay_seconds=0, fault_injection=True)
    await gateway.settle(_txn("txn_abc", attempts=1))
