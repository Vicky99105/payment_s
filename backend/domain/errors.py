"""Domain errors. The HTTP layer maps these to status codes in one place (api/errors.py)."""


class DomainError(Exception):
    """Base class for errors the service raises on purpose."""


class PersistenceError(DomainError):
    """The database could not complete an operation."""


class EnqueueError(DomainError):
    """The task queue rejected or could not receive a message."""


class SettlementError(DomainError):
    """The external settlement call failed. Retryable."""


class SettlementRetry(DomainError):
    """Processing must be retried after `delay_seconds`. The worker turns this into a queue retry."""

    def __init__(self, delay_seconds: float, reason: str = "") -> None:
        super().__init__(reason or f"retry in {delay_seconds}s")
        self.delay_seconds = delay_seconds
