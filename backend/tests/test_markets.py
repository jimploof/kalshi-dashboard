import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_markets_placeholder_shape(async_client: AsyncClient) -> None:
    response = await async_client.get("/api/markets/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "scaffold"
    assert isinstance(data["markets"], list)
    assert "connections" in data
    assert "postgres" in data["connections"]
    assert "redis" in data["connections"]


@pytest.mark.asyncio
async def test_markets_reports_connections_up(async_client: AsyncClient) -> None:
    """Connections are mocked to succeed — both should report True."""
    response = await async_client.get("/api/markets/")
    data = response.json()
    assert data["connections"]["postgres"] is True
    assert data["connections"]["redis"] is True
