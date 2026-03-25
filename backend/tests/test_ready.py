"""Tests for the /api/ready readiness endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_ready_returns_200_when_initialized(async_client: AsyncClient) -> None:
    """When both pg_ready and redis_ready are True, the endpoint returns 200 + ready=true."""
    response = await async_client.get("/api/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is True
    assert data["checks"]["postgres"] is True
    assert data["checks"]["redis"] is True


@pytest.mark.asyncio
async def test_ready_returns_503_when_not_initialized() -> None:
    """When readiness flags are absent (not set by lifespan), the endpoint returns 503."""
    # Ensure no state flags are present from a prior test.
    for attr in ("pg_ready", "redis_ready", "pg_pool", "redis"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["ready"] is False
    assert data["checks"]["postgres"] is False
    assert data["checks"]["redis"] is False
