import asyncio

from backend.domain.errors import SettlementError
from backend.domain.models import Transaction

FAULT_INJECTION_PREFIX = "faultinject_"


class DefaultSettlementGateway:
    """Simulated settlement: a fixed delay. Optional fault injection fails the first attempt of `faultinject_*` ids."""

    def __init__(self, delay_seconds: float, fault_injection: bool = False) -> None:
        self._delay_seconds = delay_seconds
        self._fault_injection = fault_injection

    async def settle(self, transaction: Transaction) -> None:
        if (
            self._fault_injection
            and transaction.transaction_id.startswith(FAULT_INJECTION_PREFIX)
            and transaction.attempts == 1
        ):
            raise SettlementError("injected settlement fault")
        await asyncio.sleep(self._delay_seconds)
