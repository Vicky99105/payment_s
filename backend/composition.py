"""Composition root: the only module that imports Default* implementations and wires them together."""

import logging
from functools import lru_cache

from backend.config import Settings
from backend.container import Container
from backend.database.pool import LazyPool
from backend.database.repositories.transaction_repository import DefaultTransactionRepository
from backend.integrations.queue.vercel_queue import DefaultTaskQueue
from backend.integrations.settlement.simulated import DefaultSettlementGateway
from backend.security.api_keys import DefaultApiKeyAuthenticator
from backend.security.webhook_signature import DefaultWebhookSignatureVerifier
from backend.services.ingestion.service import DefaultWebhookIngestionService
from backend.services.processing.contract import TransactionProcessor
from backend.services.processing.service import DefaultTransactionProcessor
from backend.services.query.service import DefaultTransactionQueryService

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _pool(database_url: str) -> LazyPool:
    return LazyPool(database_url)


def build_container(settings: Settings) -> Container:
    pool = _pool(settings.database_url)
    repository = DefaultTransactionRepository(pool.get)
    queue = DefaultTaskQueue(settings.queue_topic)

    async def warm_up() -> None:
        # Pay connection and queue-token setup at startup, not on the first webhook (phase 0: ~630ms cold).
        # Best effort: a dependency that is down must not stop the app from starting and serving health checks.
        try:
            await pool.get()
        except Exception:
            logger.warning("database warm-up failed; the pool will be created on first use")
        await queue.warm()

    return Container(
        settings=settings,
        ingestion=DefaultWebhookIngestionService(repository, queue),
        query=DefaultTransactionQueryService(repository),
        webhook_verifier=DefaultWebhookSignatureVerifier(settings.webhook_signing_secret, settings.signature_tolerance_seconds),
        api_key_authenticator=DefaultApiKeyAuthenticator(settings.api_keys),
        on_startup=[warm_up],
        on_shutdown=[pool.close],
    )


def build_processor(settings: Settings) -> TransactionProcessor:
    repository = DefaultTransactionRepository(_pool(settings.database_url).get)
    gateway = DefaultSettlementGateway(settings.settlement_delay_seconds, settings.settlement_fault_injection)
    return DefaultTransactionProcessor(repository, gateway)
