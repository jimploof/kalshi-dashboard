"""
Shared pytest fixtures.

The `async_client` fixture sets mock connection handles directly on `app.state`
so the /api/markets/ connection-status fields work in tests.  It also patches
asyncpg and redis at the lifespan import site as a safety net in case the
lifespan is ever run inside the test harness.
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    mock_pool = AsyncMock()
    mock_pool.close = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.aclose = AsyncMock()

    # ASGITransport does not run the ASGI lifespan, so we set state directly.
    app.state.pg_pool = mock_pool
    app.state.redis = mock_redis

    with (
        patch("app.lifespan.asyncpg.create_pool", return_value=mock_pool),
        patch("app.lifespan.aioredis.from_url", return_value=mock_redis),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    # Clean up state attributes so tests don't bleed into each other.
    for attr in ("pg_pool", "redis"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)
