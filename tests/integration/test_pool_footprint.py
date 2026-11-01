"""The pooler caps client connections (200 on this plan), shared by every serverless instance.

An instance must hold connections only while it uses them: a worker sleeping through
a 30s settlement, or an idle warm instance, must hold none.
"""

import asyncio

import pytest

from backend.database.pool import IDLE_CONNECTION_LIFETIME_SECONDS, MAX_SIZE, create_pool
from backend.config import Settings

pytestmark = pytest.mark.integration


async def test_idle_pool_releases_every_connection() -> None:
    pool = await create_pool(Settings().database_url)
    try:
        await asyncio.gather(*[pool.fetchval("select pg_sleep(0.2)") for _ in range(MAX_SIZE)])
        assert pool.get_size() == MAX_SIZE
        await asyncio.sleep(IDLE_CONNECTION_LIFETIME_SECONDS + 2)
        assert pool.get_size() == 0
    finally:
        await pool.close()


def test_pool_never_exceeds_a_small_per_instance_cap() -> None:
    assert MAX_SIZE <= 2
