"""Shared test helpers: webhook signing and API key fixtures."""

import hashlib
import hmac
import json
import time
from decimal import Decimal

from backend.domain.models import TransactionWebhook

TEST_SIGNING_SECRET = "test-signing-secret"
READER_KEY = "test-reader-key"
NO_SCOPE_KEY = "test-no-scope-key"


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


TEST_API_KEYS_JSON = json.dumps(
    {
        sha256_hex(READER_KEY): {"name": "reviewer", "scopes": ["transactions:read"]},
        sha256_hex(NO_SCOPE_KEY): {"name": "no-scope", "scopes": []},
    }
)


def sign(raw_body: bytes, secret: str = TEST_SIGNING_SECRET, timestamp: int | None = None) -> dict[str, str]:
    """Headers for a signed webhook request."""
    ts = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(secret.encode(), ts.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return {"X-Webhook-Timestamp": ts, "X-Webhook-Signature": f"sha256={digest}"}


def webhook_body(transaction_id: str = "txn_abc123def456", **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "transaction_id": transaction_id,
        "source_account": "acc_user_789",
        "destination_account": "acc_merchant_456",
        "amount": 1500,
        "currency": "INR",
    }
    body.update(overrides)
    return body


def make_event(transaction_id: str = "txn_abc123def456") -> TransactionWebhook:
    return TransactionWebhook(
        transaction_id=transaction_id,
        source_account="acc_user_789",
        destination_account="acc_merchant_456",
        amount=Decimal("1500"),
        currency="INR",
    )
