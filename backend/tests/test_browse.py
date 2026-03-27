"""Tests for app/routers/browse.py — DB-backed browse routes.

All DB and Redis dependencies are overridden via app.dependency_overrides.
No real database or Redis connections are made.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_db, get_redis
from app.main import app

_SAMPLE_SERIES_ROW = {
    "ticker": "KXBTCD",
    "title": "Bitcoin Daily",
    "category": "Crypto",
    "tags": ["bitcoin"],
    "frequency": "daily",
    "fetched_at": None,
}

_SAMPLE_EVENT_ROW = {
    "event_ticker": "KXBTCD-26MAR",
    "series_ticker": "KXBTCD",
    "title": "Bitcoin March 26",
    "sub_title": None,
    "category": "Crypto",
    "mutually_exclusive": True,
    "status": "open",
    "fetched_at": None,
}

_SAMPLE_MARKET_ROW = {
    "ticker": "KXBTCD-26MAR-T95000",
    "event_ticker": "KXBTCD-26MAR",
    "market_type": "binary",
    "yes_sub_title": "Above $95,000",
    "no_sub_title": "At or below $95,000",
    "title": None,
    "subtitle": None,
    "status": "open",
    "open_time": None,
    "close_time": None,
    "yes_bid_dollars": "0.55",
    "yes_ask_dollars": "0.57",
    "last_price_dollars": "0.56",
    "volume_fp": "1000",
    "volume_24h_fp": "200",
    "open_interest_fp": "500",
    "fetched_at": None,
}


def _mock_pool() -> AsyncMock:
    pool = AsyncMock()
    return pool


def _mock_redis(last_run: str | None = "2026-03-27T12:00:00+00:00") -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=last_run)
    return redis


@pytest.fixture
async def browse_client():
    mock_pool = _mock_pool()
    mock_redis = _mock_redis()

    app.dependency_overrides[get_db] = lambda: mock_pool
    app.dependency_overrides[get_redis] = lambda: mock_redis

    # Set required app state so the ASGITransport doesn't hit missing state
    app.state.pg_pool = mock_pool
    app.state.redis = mock_redis
    app.state.pg_ready = True
    app.state.redis_ready = True

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, mock_pool, mock_redis

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_redis, None)


# ---------------------------------------------------------------------------
# GET /api/browse/series
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browse_series_returns_series_from_repo(browse_client) -> None:
    client, pool, redis = browse_client
    with patch(
        "app.routers.browse.series_repo.get_series",
        new_callable=AsyncMock,
        return_value=[_SAMPLE_SERIES_ROW],
    ):
        resp = await client.get("/api/browse/series")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["series"]) == 1
    assert body["series"][0]["ticker"] == "KXBTCD"


@pytest.mark.asyncio
async def test_browse_series_category_forwarded_to_repo(browse_client) -> None:
    client, pool, redis = browse_client
    with patch(
        "app.routers.browse.series_repo.get_series",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_get:
        await client.get("/api/browse/series?category=Crypto")

    mock_get.assert_called_once_with(pool, category="Crypto")


# ---------------------------------------------------------------------------
# GET /api/browse/events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browse_events_returns_events_from_repo(browse_client) -> None:
    client, pool, redis = browse_client
    with patch(
        "app.routers.browse.events_repo.get_events",
        new_callable=AsyncMock,
        return_value=([_SAMPLE_EVENT_ROW], None),
    ):
        resp = await client.get("/api/browse/events?status=open")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["events"]) == 1
    assert body["events"][0]["event_ticker"] == "KXBTCD-26MAR"
    assert body["hydration_last_run"] is not None


# ---------------------------------------------------------------------------
# GET /api/browse/markets/{ticker} — found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browse_market_detail_found(browse_client) -> None:
    client, pool, redis = browse_client
    with patch(
        "app.routers.browse.events_repo.get_market",
        new_callable=AsyncMock,
        return_value=_SAMPLE_MARKET_ROW,
    ):
        resp = await client.get("/api/browse/markets/KXBTCD-26MAR-T95000")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["market"]["ticker"] == "KXBTCD-26MAR-T95000"
    assert body["market"]["yes_bid_dollars"] == "0.55"


# ---------------------------------------------------------------------------
# GET /api/browse/markets/{ticker} — not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browse_market_detail_not_found(browse_client) -> None:
    client, pool, redis = browse_client
    with patch(
        "app.routers.browse.events_repo.get_market",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = await client.get("/api/browse/markets/FAKE-TICKER")

    assert resp.status_code == 404
    body = resp.json()
    assert body["status"] == "not_found"
    assert body["market"] is None
