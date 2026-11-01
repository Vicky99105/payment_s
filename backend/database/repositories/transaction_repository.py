import json
from collections.abc import Awaitable, Callable
from typing import Protocol

import asyncpg

from backend.domain.errors import PersistenceError
from backend.domain.models import Transaction, TransactionStatus, TransactionWebhook


class TransactionRepository(Protocol):
    async def ingest(self, event: TransactionWebhook) -> tuple[Transaction, bool]:
        """Log the delivery and insert the transaction if absent, atomically, in one round trip.

        Returns the current row and True if this call created it.
        Raises PersistenceError.
        """
        ...

    async def get(self, transaction_id: str) -> Transaction | None: ...

    async def record_attempt(self, transaction_id: str) -> Transaction | None:
        """Increment `attempts` if the row is PROCESSING. Returns the current row (updated or not), None if absent."""
        ...

    async def record_failure(self, transaction_id: str, error: str) -> None:
        """Store the latest processing error on the row."""
        ...

    async def mark_processed(self, transaction_id: str) -> bool:
        """PROCESSING -> PROCESSED with processed_at=now(). True only for the call that made the transition."""
        ...


# --- Implementation (asyncpg). Callers import the Protocol above, never this class. ---

MAX_ERROR_LENGTH = 500

_DB_ERRORS = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError)

_COLUMNS = (
    "transaction_id, source_account, destination_account, amount, currency, status, "
    "attempts, last_error, created_at, updated_at, processed_at"
)

# One round trip: log the delivery, insert-if-absent, and return the current row.
# `created` is true only for the row this statement inserted.
_INGEST_SQL = f"""
WITH delivery AS (
    INSERT INTO webhook_deliveries (transaction_id, payload) VALUES ($1, $6::jsonb)
),
inserted AS (
    INSERT INTO transactions (transaction_id, source_account, destination_account, amount, currency)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (transaction_id) DO NOTHING
    RETURNING {_COLUMNS}
)
SELECT {_COLUMNS}, true AS created FROM inserted
UNION ALL
SELECT {_COLUMNS}, false AS created FROM transactions
WHERE transaction_id = $1 AND NOT EXISTS (SELECT 1 FROM inserted)
"""

_GET_SQL = f"SELECT {_COLUMNS} FROM transactions WHERE transaction_id = $1"

_RECORD_ATTEMPT_SQL = f"""
UPDATE transactions SET attempts = attempts + 1, updated_at = now()
WHERE transaction_id = $1 AND status = 'PROCESSING'
RETURNING {_COLUMNS}
"""

_RECORD_FAILURE_SQL = """
UPDATE transactions SET last_error = $2, updated_at = now() WHERE transaction_id = $1
"""

_MARK_PROCESSED_SQL = """
UPDATE transactions SET status = 'PROCESSED', processed_at = now(), updated_at = now()
WHERE transaction_id = $1 AND status = 'PROCESSING'
"""


def _to_transaction(row: asyncpg.Record) -> Transaction:
    return Transaction(
        transaction_id=row["transaction_id"],
        source_account=row["source_account"],
        destination_account=row["destination_account"],
        amount=row["amount"],
        currency=row["currency"].strip(),
        status=TransactionStatus(row["status"]),
        attempts=row["attempts"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        processed_at=row["processed_at"],
    )


def _payload(event: TransactionWebhook) -> str:
    return json.dumps(
        {
            "transaction_id": event.transaction_id,
            "source_account": event.source_account,
            "destination_account": event.destination_account,
            "amount": str(event.amount),
            "currency": event.currency,
        }
    )


class DefaultTransactionRepository:
    def __init__(self, pool_provider: Callable[[], Awaitable[asyncpg.Pool]]) -> None:
        self._pool_provider = pool_provider

    async def ingest(self, event: TransactionWebhook) -> tuple[Transaction, bool]:
        try:
            pool = await self._pool_provider()
            row = await pool.fetchrow(
                _INGEST_SQL,
                event.transaction_id,
                event.source_account,
                event.destination_account,
                event.amount,
                event.currency,
                _payload(event),
            )
            if row is None:
                # Concurrent first deliveries: ON CONFLICT waited for the winner to commit, but this
                # statement's snapshot predates that commit, so its SELECT branch saw nothing.
                # The row is committed now; read it with a fresh snapshot.
                row = await pool.fetchrow(_GET_SQL, event.transaction_id)
                if row is None:
                    raise PersistenceError("transaction row missing after ingest")
                return _to_transaction(row), False
        except _DB_ERRORS as exc:
            raise PersistenceError("database operation failed") from exc
        return _to_transaction(row), bool(row["created"])

    async def get(self, transaction_id: str) -> Transaction | None:
        try:
            pool = await self._pool_provider()
            row = await pool.fetchrow(_GET_SQL, transaction_id)
        except _DB_ERRORS as exc:
            raise PersistenceError("database operation failed") from exc
        return None if row is None else _to_transaction(row)

    async def record_attempt(self, transaction_id: str) -> Transaction | None:
        try:
            pool = await self._pool_provider()
            row = await pool.fetchrow(_RECORD_ATTEMPT_SQL, transaction_id)
            if row is None:
                row = await pool.fetchrow(_GET_SQL, transaction_id)
        except _DB_ERRORS as exc:
            raise PersistenceError("database operation failed") from exc
        return None if row is None else _to_transaction(row)

    async def record_failure(self, transaction_id: str, error: str) -> None:
        try:
            pool = await self._pool_provider()
            await pool.execute(_RECORD_FAILURE_SQL, transaction_id, error[:MAX_ERROR_LENGTH])
        except _DB_ERRORS as exc:
            raise PersistenceError("database operation failed") from exc

    async def mark_processed(self, transaction_id: str) -> bool:
        try:
            pool = await self._pool_provider()
            status = await pool.execute(_MARK_PROCESSED_SQL, transaction_id)
        except _DB_ERRORS as exc:
            raise PersistenceError("database operation failed") from exc
        return status == "UPDATE 1"
