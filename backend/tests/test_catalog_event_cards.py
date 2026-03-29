import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import AsyncClient

from app.dependencies import get_kalshi_client, get_redis
from app.main import app
from app.services.kalshi.rest_client import KalshiRestClient


def _snapshot_payload(*, built_at: datetime | None = None) -> str:
    built = built_at or datetime.now(timezone.utc)
    return json.dumps(
        {
            "snapshot_id": "snap-1",
            "built_at": built.isoformat(),
            "cards": [
                {
                    "event_ticker": "E1",
                    "series_ticker": "KXNBA",
                    "category": "Sports",
                    "title": "Alpha",
                    "sub_title": "Tonight",
                    "mutually_exclusive": False,
                    "last_updated_ts": "2026-03-29T10:00:00Z",
                    "market_count": 1,
                    "nearest_close_time": "2026-03-29T12:00:00Z",
                    "total_volume_fp": "20.00",
                    "total_open_interest_fp": "7.00",
                    "top_markets": [
                        {
                            "ticker": "M1",
                            "event_ticker": "E1",
                            "market_type": "binary",
                            "yes_sub_title": "Yes",
                            "no_sub_title": "No",
                            "status": "open",
                            "close_time": "2026-03-29T12:00:00Z",
                            "yes_bid_dollars": "0.45",
                            "yes_ask_dollars": "0.47",
                            "last_price_dollars": "0.46",
                            "volume_fp": "20.00",
                            "open_interest_fp": "7.00",
                        }
                    ],
                },
                {
                    "event_ticker": "E2",
                    "series_ticker": "KXNBA",
                    "category": "Sports",
                    "title": "Beta",
                    "sub_title": None,
                    "mutually_exclusive": True,
                    "last_updated_ts": "2026-03-29T11:00:00Z",
                    "market_count": 1,
                    "nearest_close_time": None,
                    "total_volume_fp": "5.00",
                    "total_open_interest_fp": "3.00",
                    "top_markets": [],
                },
            ],
        }
    )


def _mock_redis_snapshot(payload: str | None) -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=payload)
    redis.set = AsyncMock(return_value=True)
    return redis


def _mock_kalshi_client() -> MagicMock:
    client = MagicMock(spec=KalshiRestClient)
    client.get_events = AsyncMock(return_value={"events": [], "cursor": None})
    return client


@pytest.mark.asyncio
async def test_event_cards_success_from_cached_snapshot(async_client: AsyncClient) -> None:
    mock_redis = _mock_redis_snapshot(_snapshot_payload())
    mock_client = _mock_kalshi_client()
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/event-cards?category=Sports")
    finally:
        app.dependency_overrides.pop(get_redis, None)
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["total"] == 2
    assert data["cards"][0]["event_ticker"] == "E1"
    assert mock_client.get_events.await_count == 0


@pytest.mark.asyncio
async def test_event_cards_422_for_invalid_cursor(async_client: AsyncClient) -> None:
    mock_redis = _mock_redis_snapshot(_snapshot_payload())
    mock_client = _mock_kalshi_client()
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/event-cards?category=Sports&cursor=bad-cursor")
    finally:
        app.dependency_overrides.pop(get_redis, None)
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_event_cards_serve_stale_snapshot(async_client: AsyncClient) -> None:
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=180)
    mock_redis = _mock_redis_snapshot(_snapshot_payload(built_at=stale_time))
    mock_client = _mock_kalshi_client()
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/event-cards?category=Sports")
    finally:
        app.dependency_overrides.pop(get_redis, None)
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    assert response.json()["stale"] is True


@pytest.mark.asyncio
async def test_event_cards_502_on_hard_miss_and_upstream_failure(async_client: AsyncClient) -> None:
    mock_redis = _mock_redis_snapshot(None)
    mock_client = MagicMock(spec=KalshiRestClient)
    mock_client.get_events = AsyncMock(side_effect=httpx.ConnectError("boom"))
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/event-cards?category=Sports")
    finally:
        app.dependency_overrides.pop(get_redis, None)
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["cards"] == []


@pytest.mark.asyncio
async def test_event_cards_422_for_cursor_context_mismatch(async_client: AsyncClient) -> None:
    """A well-formed cursor bound to a different category must return 422."""
    from app.services.catalog.event_card_cursor import EventCardCursorContext, encode_cursor

    wrong_context = EventCardCursorContext(
        snapshot_id="snap-1",
        category="Crypto",  # snapshot has category="Sports"
        series_ticker=None,
        sort_by="total_volume",
        sort_order="desc",
    )
    cursor = encode_cursor(wrong_context, 0)
    mock_redis = _mock_redis_snapshot(_snapshot_payload())
    mock_client = _mock_kalshi_client()
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get(
            f"/api/catalog/event-cards?category=Sports&cursor={cursor}"
        )
    finally:
        app.dependency_overrides.pop(get_redis, None)
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_event_cards_category_filter_returns_empty_for_non_matching(
    async_client: AsyncClient,
) -> None:
    """Querying a category that has no cards in the snapshot returns total=0."""
    mock_redis = _mock_redis_snapshot(_snapshot_payload())  # snapshot only has "Sports" cards
    mock_client = _mock_kalshi_client()
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/event-cards?category=Crypto")
    finally:
        app.dependency_overrides.pop(get_redis, None)
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["total"] == 0
    assert data["cards"] == []