"""HMAC-SHA256 verification of payment-processor webhooks."""

import hashlib
import hmac
import re
import time
from collections.abc import Callable

from backend.security.contract import AuthenticationError, Principal, Scope

_PROCESSOR = Principal(name="payment-processor", scopes=frozenset({Scope.WEBHOOKS_WRITE}))
_TIMESTAMP = re.compile(r"[0-9]{1,12}")
_SIGNATURE = re.compile(r"sha256=([0-9a-fA-F]{64})")


class DefaultWebhookSignatureVerifier:
    """Verifies `sha256=<hex>` of HMAC-SHA256(secret, b"<timestamp>." + raw_body). Fails closed without a secret."""

    def __init__(self, secret: str, tolerance_seconds: int = 300, clock: Callable[[], float] = time.time) -> None:
        self._secret = secret.encode()
        self._tolerance = tolerance_seconds
        self._clock = clock

    def verify(self, raw_body: bytes, timestamp: str | None, signature: str | None) -> Principal:
        if not self._secret:
            raise AuthenticationError("webhook signing is not configured")
        if not timestamp or not signature:
            raise AuthenticationError("missing signature headers")
        if not _TIMESTAMP.fullmatch(timestamp) or abs(self._clock() - int(timestamp)) > self._tolerance:
            raise AuthenticationError("stale or invalid timestamp")
        match = _SIGNATURE.fullmatch(signature)
        if match is None:
            raise AuthenticationError("invalid signature")
        expected = hmac.new(self._secret, timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, match.group(1).lower()):
            raise AuthenticationError("invalid signature")
        return _PROCESSOR
