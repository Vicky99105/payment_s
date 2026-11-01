"""Queue message handling, kept free of subscriber wiring so it is testable."""

import logging

from vercel.queue import RetryAfter

from backend.domain.errors import PersistenceError, SettlementRetry
from backend.domain.models import ProcessOutcome
from backend.services.processing.contract import TransactionProcessor

logger = logging.getLogger(__name__)

DB_RETRY_DELAY_SECONDS = 10


async def handle_transaction_message(processor: TransactionProcessor, transaction_id: str) -> ProcessOutcome:
    """Process one queued transaction. A SettlementRetry becomes a delayed queue redelivery."""
    try:
        outcome = await processor.process(transaction_id)
    except SettlementRetry as retry:
        logger.warning(
            "transaction retry scheduled",
            extra={"transaction_id": transaction_id, "outcome": "RETRY", "delay_seconds": retry.delay_seconds},
        )
        raise RetryAfter(retry.delay_seconds) from retry
    except PersistenceError as err:
        # Transient (e.g. the pooler's connection cap). Retry soon instead of waiting out the 5-minute lease.
        logger.warning(
            "database unavailable, retry scheduled",
            extra={"transaction_id": transaction_id, "outcome": "RETRY", "delay_seconds": DB_RETRY_DELAY_SECONDS},
        )
        raise RetryAfter(DB_RETRY_DELAY_SECONDS) from err
    logger.info("transaction handled", extra={"transaction_id": transaction_id, "outcome": outcome.value})
    return outcome
