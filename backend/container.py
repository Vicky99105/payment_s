"""The seam between wiring and the HTTP app: create_app() receives a Container and never builds dependencies itself."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from backend.config import Settings
from backend.security.contract import ApiKeyAuthenticator, WebhookSignatureVerifier
from backend.services.ingestion.contract import WebhookIngestionService
from backend.services.query.contract import TransactionQueryService


@dataclass
class Container:
    settings: Settings
    ingestion: WebhookIngestionService
    query: TransactionQueryService
    webhook_verifier: WebhookSignatureVerifier
    api_key_authenticator: ApiKeyAuthenticator
    on_startup: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    on_shutdown: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
