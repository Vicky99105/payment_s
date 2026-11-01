"""asyncpg pool for Supabase Postgres behind the Supavisor transaction pooler (port 6543).

The transaction pooler hands each statement to any backend connection, so server-side
prepared statements cannot be reused: statement_cache_size=0 is mandatory.
"""

import asyncio
from typing import Literal
from urllib.parse import parse_qs, urlsplit

import asyncpg

MIN_SIZE = 1
MAX_SIZE = 5
COMMAND_TIMEOUT_SECONDS = 5.0
CONNECT_TIMEOUT_SECONDS = 5.0


def _url_sets_sslmode(database_url: str) -> bool:
    return "sslmode" in parse_qs(urlsplit(database_url).query)


async def create_pool(database_url: str) -> asyncpg.Pool:
    ssl: Literal["require"] | None = None if _url_sets_sslmode(database_url) else "require"
    pool = await asyncpg.create_pool(
        database_url,
        min_size=MIN_SIZE,
        max_size=MAX_SIZE,
        statement_cache_size=0,
        command_timeout=COMMAND_TIMEOUT_SECONDS,
        timeout=CONNECT_TIMEOUT_SECONDS,
        ssl=ssl,
    )
    assert pool is not None
    return pool


async def close_pool(pool: asyncpg.Pool) -> None:
    await pool.close()


class LazyPool:
    """Creates the pool on first use. The serverless runtime may not run ASGI lifespan hooks.

    A failed creation is not cached: the next `get()` tries again.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> asyncpg.Pool:
        if self._pool is not None:
            return self._pool
        async with self._lock:
            if self._pool is None:
                self._pool = await create_pool(self._database_url)
            return self._pool

    async def close(self) -> None:
        async with self._lock:
            if self._pool is not None:
                pool, self._pool = self._pool, None
                await close_pool(pool)
