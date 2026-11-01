"""Integration fixtures: real Supabase Postgres. Skipped unless DATABASE_URL is set (env or .env)."""

import uuid
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest

from backend.config import Settings
from backend.database.pool import close_pool, create_pool

ID_PREFIX = "itest_"
DATABASE_URL = Settings().database_url


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" not in str(item.path).replace("\\", "/"):
            continue
        item.add_marker(pytest.mark.integration)
        if not DATABASE_URL and "test_task_queue" not in item.path.name:
            item.add_marker(pytest.mark.skip(reason="DATABASE_URL is not set"))


def new_id() -> str:
    return f"{ID_PREFIX}{uuid.uuid4().hex}"


async def _delete_test_rows() -> None:
    conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0, ssl="require")
    try:
        like = f"{ID_PREFIX}%"
        await conn.execute("DELETE FROM webhook_deliveries WHERE transaction_id LIKE $1", like)
        await conn.execute("DELETE FROM transactions WHERE transaction_id LIKE $1", like)
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_rows() -> Iterator[None]:
    """Deletes every `itest_*` row after the session (and before, in case a prior run crashed)."""
    import asyncio

    if not DATABASE_URL:
        yield
        return
    asyncio.run(_delete_test_rows())
    yield
    asyncio.run(_delete_test_rows())


@pytest.fixture
async def pool() -> AsyncIterator[asyncpg.Pool]:
    p = await create_pool(DATABASE_URL)
    try:
        yield p
    finally:
        await close_pool(p)
