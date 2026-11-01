"""HTTP layer through the real app factory, with services on fakes and the real security modules."""

import json
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.config import Settings
from backend.container import Container
from backend.domain.models import TransactionWebhook
from backend.security.api_keys import DefaultApiKeyAuthenticator
from backend.security.webhook_signature import DefaultWebhookSignatureVerifier
from backend.services.ingestion.service import DefaultWebhookIngestionService
from backend.services.query.service import DefaultTransactionQueryService
from tests.fakes import FakeTaskQueue, FakeTransactionRepository
from tests.helpers import (
    NO_SCOPE_KEY,
    READER_KEY,
    TEST_API_KEYS_JSON,
    TEST_SIGNING_SECRET,
    make_event,
    sign,
    webhook_body,
)

ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class ExplodingQuery:
    async def get(self, transaction_id: str) -> None:
        raise RuntimeError("secret internal detail: password=hunter2")


class Harness:
    def __init__(self, env: str = "test") -> None:
        self.repo = FakeTransactionRepository()
        self.queue = FakeTaskQueue()
        settings = Settings(_env_file=None, env=env, webhook_signing_secret=TEST_SIGNING_SECRET, api_keys=TEST_API_KEYS_JSON)  # type: ignore[call-arg]
        self.container = Container(
            settings=settings,
            ingestion=DefaultWebhookIngestionService(self.repo, self.queue),
            query=DefaultTransactionQueryService(self.repo),
            webhook_verifier=DefaultWebhookSignatureVerifier(TEST_SIGNING_SECRET),
            api_key_authenticator=DefaultApiKeyAuthenticator(TEST_API_KEYS_JSON),
        )
        self.client = TestClient(create_app(self.container), raise_server_exceptions=False)

    def post_webhook(self, body: object, headers: dict[str, str] | None = None, signed: bool = True) -> object:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        h = {"content-type": "application/json", **(sign(raw) if signed else {}), **(headers or {})}
        return self.client.post("/v1/webhooks/transactions", content=raw, headers=h)

    def get_txn(self, transaction_id: str, key: str | None = READER_KEY) -> object:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        return self.client.get(f"/v1/transactions/{transaction_id}", headers=headers)


@pytest.fixture
def h() -> Iterator[Harness]:
    yield Harness()


# --- webhook: happy path and validation -------------------------------------------------

def test_signed_valid_webhook_returns_202_with_ack(h: Harness) -> None:
    r = h.post_webhook(webhook_body("txn_1"))
    assert r.status_code == 202
    assert r.json() == {"status": "accepted", "transaction_id": "txn_1"}
    assert h.queue.delivered == ["txn_1"]
    assert r.headers["x-request-id"]


def test_duplicate_webhooks_all_return_202_and_store_once(h: Harness) -> None:
    for _ in range(3):
        assert h.post_webhook(webhook_body("txn_dup")).status_code == 202
    assert len(h.repo.rows) == 1
    assert h.queue.delivered == ["txn_dup"]


@pytest.mark.parametrize(
    "body",
    [
        {k: v for k, v in webhook_body().items() if k != "amount"},
        webhook_body(amount=0),
        webhook_body(amount=-5),
        webhook_body(amount="1.234"),
        webhook_body(currency="inr"),
        webhook_body(currency="RUPEE"),
        webhook_body(transaction_id="bad id with spaces"),
        webhook_body(extra_field="nope"),
    ],
    ids=["missing-amount", "zero-amount", "negative-amount", "3dp-amount", "lowercase-currency", "long-currency", "bad-id", "extra-field"],
)
def test_invalid_body_returns_422_without_echoing_input(h: Harness, body: dict[str, object]) -> None:
    r = h.post_webhook(body)
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_request"
    assert "RUPEE" not in r.text and "bad id with spaces" not in r.text
    assert h.repo.rows == {}


def test_malformed_json_returns_422(h: Harness) -> None:
    assert h.post_webhook(b"{not json").status_code == 422


def test_body_over_16kb_returns_413(h: Harness) -> None:
    raw = json.dumps(webhook_body(padding="x" * 17_000)).encode()
    r = h.post_webhook(raw)
    assert r.status_code == 413
    assert r.json()["error"] == "payload_too_large"


def test_persistence_failure_returns_503_not_202(h: Harness) -> None:
    h.repo.fail_next_ingest = True
    r = h.post_webhook(webhook_body("txn_db_down"))
    assert r.status_code == 503
    assert r.headers["retry-after"] == "5"
    assert h.queue.calls == []


def test_queue_failure_returns_503_and_retry_succeeds(h: Harness) -> None:
    h.queue.failures_remaining = 1
    assert h.post_webhook(webhook_body("txn_q")).status_code == 503
    assert h.post_webhook(webhook_body("txn_q")).status_code == 202
    assert h.queue.delivered == ["txn_q"]


# --- webhook: authentication ------------------------------------------------------------

def test_unsigned_webhook_returns_401_before_validation(h: Harness) -> None:
    r = h.post_webhook({"garbage": True}, signed=False)
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_webhook_signed_with_wrong_secret_returns_401(h: Harness) -> None:
    raw = json.dumps(webhook_body()).encode()
    r = h.client.post("/v1/webhooks/transactions", content=raw, headers={"content-type": "application/json", **sign(raw, secret="wrong")})
    assert r.status_code == 401


def test_webhook_body_tampered_after_signing_returns_401(h: Harness) -> None:
    raw = json.dumps(webhook_body(amount=10)).encode()
    tampered = json.dumps(webhook_body(amount=10_000)).encode()
    r = h.client.post("/v1/webhooks/transactions", content=tampered, headers={"content-type": "application/json", **sign(raw)})
    assert r.status_code == 401
    assert h.repo.rows == {}


def test_replayed_webhook_with_stale_timestamp_returns_401(h: Harness) -> None:
    import time

    raw = json.dumps(webhook_body()).encode()
    r = h.client.post("/v1/webhooks/transactions", content=raw, headers={"content-type": "application/json", **sign(raw, timestamp=int(time.time()) - 301)})
    assert r.status_code == 401


# --- query endpoint ---------------------------------------------------------------------

def test_get_without_key_returns_401_with_www_authenticate(h: Harness) -> None:
    r = h.get_txn("txn_1", key=None)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_get_with_unknown_key_returns_401(h: Harness) -> None:
    assert h.get_txn("txn_1", key="not-a-real-key").status_code == 401


def test_get_with_key_lacking_scope_returns_403(h: Harness) -> None:
    assert h.get_txn("txn_1", key=NO_SCOPE_KEY).status_code == 403


def test_get_returns_spec_array_shape_while_processing(h: Harness) -> None:
    h.post_webhook(webhook_body("txn_shape"))
    r = h.get_txn("txn_shape")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list) and len(body) == 1
    item = body[0]
    assert set(item) == {"transaction_id", "source_account", "destination_account", "amount", "currency", "status", "created_at", "processed_at"}
    assert item["status"] == "PROCESSING"
    assert item["processed_at"] is None
    assert item["amount"] == 1500
    assert ISO_Z.match(item["created_at"])


def test_get_after_processing_shows_processed_at(h: Harness) -> None:
    import asyncio

    h.post_webhook(webhook_body("txn_done", amount=150.5, currency="USD"))
    asyncio.run(h.repo.mark_processed("txn_done"))
    item = h.get_txn("txn_done").json()[0]
    assert item["status"] == "PROCESSED"
    assert item["amount"] == 150.5
    assert ISO_Z.match(item["processed_at"])


def test_get_unknown_id_returns_404(h: Harness) -> None:
    r = h.get_txn("txn_missing")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


def test_get_with_invalid_id_format_returns_422(h: Harness) -> None:
    assert h.get_txn("bad%20id").status_code == 422


def test_unexpected_error_returns_generic_500_without_internals(h: Harness) -> None:
    h.container.query = ExplodingQuery()  # type: ignore[assignment]
    client = TestClient(create_app(h.container), raise_server_exceptions=False)
    r = client.get("/v1/transactions/txn_1", headers={"Authorization": f"Bearer {READER_KEY}"})
    assert r.status_code == 500
    assert r.json()["error"] == "internal_error"
    assert "hunter2" not in r.text and "RuntimeError" not in r.text


# --- health and surface -----------------------------------------------------------------

def test_health_is_public_and_iso_utc(h: Harness) -> None:
    r = h.client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "HEALTHY"
    assert ISO_Z.match(r.json()["current_time"])


def test_docs_disabled_in_production() -> None:
    prod = Harness(env="production")
    assert prod.client.get("/docs").status_code == 404
    assert prod.client.get("/openapi.json").status_code == 404


def test_docs_available_outside_production(h: Harness) -> None:
    assert h.client.get("/docs").status_code == 200


def test_event_reaches_repository_as_domain_model(h: Harness) -> None:
    h.post_webhook(webhook_body("txn_dom"))
    assert h.repo.deliveries == [make_event("txn_dom")]
    assert isinstance(h.repo.deliveries[0], TransactionWebhook)


def test_api_responses_are_never_cached_and_not_sniffable(h: Harness) -> None:
    h.post_webhook(webhook_body("txn_cache"))
    for r in (h.get_txn("txn_cache"), h.get_txn("txn_cache", key=None), h.post_webhook(webhook_body("txn_cache2"))):
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["x-content-type-options"] == "nosniff"


def test_settings_default_to_production_so_docs_are_off_unless_opted_in() -> None:
    assert Settings(_env_file=None).env == "production"  # type: ignore[call-arg]
