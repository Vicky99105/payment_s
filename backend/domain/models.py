"""Domain models. Pure data: no I/O, no framework imports."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class TransactionStatus(StrEnum):
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"


@dataclass(frozen=True)
class TransactionWebhook:
    """A validated inbound webhook, in the service's canonical format."""

    transaction_id: str
    source_account: str
    destination_account: str
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    source_account: str
    destination_account: str
    amount: Decimal
    currency: str
    status: TransactionStatus
    attempts: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None


class IngestOutcome(StrEnum):
    CREATED = "CREATED"
    """New transaction stored and enqueued."""
    DUPLICATE_IN_FLIGHT = "DUPLICATE_IN_FLIGHT"
    """Already stored and still PROCESSING; re-enqueued (the queue dedupes by transaction_id)."""
    DUPLICATE_COMPLETED = "DUPLICATE_COMPLETED"
    """Already PROCESSED; nothing enqueued."""


class ProcessOutcome(StrEnum):
    PROCESSED = "PROCESSED"
    ALREADY_PROCESSED = "ALREADY_PROCESSED"
    NOT_FOUND = "NOT_FOUND"
