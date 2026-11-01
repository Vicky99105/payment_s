from typing import Protocol

from backend.domain.models import Transaction


class SettlementGateway(Protocol):
    async def settle(self, transaction: Transaction) -> None:
        """The external settlement call (simulated: a fixed delay). Raises SettlementError on failure."""
        ...
