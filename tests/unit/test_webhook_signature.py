import pytest

from backend.security.contract import AuthenticationError, Scope, WebhookSignatureVerifier
from backend.security.webhook_signature import DefaultWebhookSignatureVerifier
from tests.helpers import TEST_SIGNING_SECRET, sign

NOW = 1_700_000_000
BODY = b'{"transaction_id":"txn_abc123def456"}'


def _verifier(secret: str = TEST_SIGNING_SECRET) -> WebhookSignatureVerifier:
    return DefaultWebhookSignatureVerifier(secret, tolerance_seconds=300, clock=lambda: float(NOW))


def _verify(headers: dict[str, str], body: bytes = BODY, secret: str = TEST_SIGNING_SECRET) -> None:
    _verifier(secret).verify(body, headers.get("X-Webhook-Timestamp"), headers.get("X-Webhook-Signature"))


def test_valid_signature_yields_payment_processor_principal() -> None:
    headers = sign(BODY, timestamp=NOW)

    principal = _verifier().verify(BODY, headers["X-Webhook-Timestamp"], headers["X-Webhook-Signature"])

    assert principal.name == "payment-processor"
    assert principal.scopes == {Scope.WEBHOOKS_WRITE}


def test_wrong_secret_is_rejected() -> None:
    with pytest.raises(AuthenticationError):
        _verify(sign(BODY, secret="other-secret", timestamp=NOW))


def test_body_tampered_after_signing_is_rejected() -> None:
    headers = sign(BODY, timestamp=NOW)
    with pytest.raises(AuthenticationError):
        _verify(headers, body=BODY + b" ")


@pytest.mark.parametrize("missing", ["X-Webhook-Timestamp", "X-Webhook-Signature"])
def test_missing_header_is_rejected(missing: str) -> None:
    headers = sign(BODY, timestamp=NOW)
    del headers[missing]
    with pytest.raises(AuthenticationError, match="missing signature headers"):
        _verify(headers)


def test_signature_without_prefix_is_rejected() -> None:
    headers = sign(BODY, timestamp=NOW)
    headers["X-Webhook-Signature"] = headers["X-Webhook-Signature"].removeprefix("sha256=")
    with pytest.raises(AuthenticationError, match="invalid signature"):
        _verify(headers)


def test_non_hex_signature_is_rejected() -> None:
    headers = sign(BODY, timestamp=NOW)
    headers["X-Webhook-Signature"] = "sha256=" + "z" * 64
    with pytest.raises(AuthenticationError, match="invalid signature"):
        _verify(headers)


def test_non_integer_timestamp_is_rejected() -> None:
    headers = sign(BODY, timestamp=NOW)
    headers["X-Webhook-Timestamp"] = "17e8"
    with pytest.raises(AuthenticationError, match="stale or invalid timestamp"):
        _verify(headers)


@pytest.mark.parametrize("offset", [-301, 301])
def test_timestamp_outside_tolerance_is_rejected(offset: int) -> None:
    with pytest.raises(AuthenticationError, match="stale or invalid timestamp"):
        _verify(sign(BODY, timestamp=NOW + offset))


def test_timestamp_inside_tolerance_is_accepted() -> None:
    _verify(sign(BODY, timestamp=NOW - 299))


def test_empty_secret_fails_closed() -> None:
    with pytest.raises(AuthenticationError, match="webhook signing is not configured"):
        _verify(sign(BODY, secret="", timestamp=NOW), secret="")
