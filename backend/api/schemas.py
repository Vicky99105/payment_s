"""HTTP contract: request and response bodies, exactly as the API exposes them."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_serializer

from backend.domain.models import Transaction, TransactionStatus, TransactionWebhook

def to_utc_z(value: datetime) -> str:
    """ISO-8601 in UTC with a `Z` suffix and millisecond precision, e.g. 2024-01-15T10:30:00.123Z."""
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_\-]{1,64}$")]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class TransactionWebhookIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: Identifier
    source_account: Identifier
    destination_account: Identifier
    amount: Annotated[Decimal, Field(gt=0, le=Decimal("1000000000000"), max_digits=15, decimal_places=2)]
    currency: CurrencyCode

    def to_domain(self) -> TransactionWebhook:
        return TransactionWebhook(
            transaction_id=self.transaction_id,
            source_account=self.source_account,
            destination_account=self.destination_account,
            amount=self.amount,
            currency=self.currency,
        )


class WebhookAck(BaseModel):
    status: Literal["accepted"] = "accepted"
    transaction_id: str


class TransactionOut(BaseModel):
    transaction_id: str
    source_account: str
    destination_account: str
    amount: float
    currency: str
    status: TransactionStatus
    created_at: datetime
    processed_at: datetime | None

    @field_serializer("created_at", "processed_at")
    def _serialize_timestamp(self, value: datetime | None) -> str | None:
        return None if value is None else to_utc_z(value)

    @classmethod
    def from_domain(cls, txn: Transaction) -> "TransactionOut":
        return cls(
            transaction_id=txn.transaction_id,
            source_account=txn.source_account,
            destination_account=txn.destination_account,
            amount=float(txn.amount),
            currency=txn.currency,
            status=txn.status,
            created_at=txn.created_at,
            processed_at=txn.processed_at,
        )


class HealthOut(BaseModel):
    status: Literal["HEALTHY"] = "HEALTHY"
    current_time: str


class ErrorOut(BaseModel):
    error: str
    detail: str | None = None
    request_id: str | None = None
