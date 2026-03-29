"""
Tests for GET /api/catalog/events and GET /api/catalog/events/{ticker}.

All tests mock KalshiRestClient via FastAPI dependency overrides; no real
network calls are made.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import AsyncClient

from app.dependencies import get_kalshi_client
from app.main import app
from app.services.kalshi.rest_client import KalshiRestClient

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_RAW_EVENTS = [
    {
        "event_ticker": "KXNBA-2026-03-28",
        "series_ticker": "KXNBA",
        "title": "NBA Mar 28 Games",
        "sub_title": "3 games scheduled",
        "category": "Sports",
        "mutually_exclusive": False,
    },
    {
        "event_ticker": "KXBTC-2026-04-01",
        "series_ticker": "KXBTC",
        "title": "Bitcoin Apr 1",
        "sub_title": None,
        "category": "Crypto",
        "mutually_exclusive": True,
    },
]

_RAW_EVENT_WITH_MARKETS = {
    "event": {
        "event_ticker": "KXNBA-2026-03-28",
        "series_ticker": "KXNBA",
        "title": "NBA Mar 28 Games",
        "sub_title": "3 games scheduled",
        "category": "Sports",
        "mutually_exclusive": False,
        "markets": [
            {
                "ticker": "KXNBA-2026-03-28-MIA",
                "event_ticker": "KXNBA-2026-03-28",
                "market_type": "binary",
                "yes_sub_title": "Miami wins",
                "no_sub_title": "Miami loses",
                "title": "Will Miami win?",
                "subtitle": None,
                "status": "open",
                "open_time": "2026-03-28T18:00:00Z",
                "close_time": "2026-03-28T22:00:00Z",
                "yes_bid_dollars": "0.54",
                "yes_ask_dollars": "0.56",
                "last_price_dollars": "0.55",
                "volume_fp": "1000.25",
                "volume_24h_fp": "500.10",
                "open_interest_fp": "300.00",
            }
        ],
    }
}


def _mock_kalshi_client_events() -> MagicMock:
    client = MagicMock(spec=KalshiRestClient)
    client.get_events = AsyncMock(return_value={"events": _RAW_EVENTS, "cursor": None})
    client.get_event = AsyncMock(return_value=_RAW_EVENT_WITH_MARKETS)
    return client


# ---------------------------------------------------------------------------
# GET /api/catalog/events — list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_list_success_shape(async_client: AsyncClient) -> None:
    """Returns status=success with events list and cursor."""
    mock_client = _mock_kalshi_client_events()
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert isinstance(data["events"], list)
    assert len(data["events"]) == 2
    assert "cursor" in data


@pytest.mark.asyncio
async def test_events_list_markets_not_included(async_client: AsyncClient) -> None:
    """List results do not include nested markets (empty list)."""
    mock_client = _mock_kalshi_client_events()
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    for event in response.json()["events"]:
        assert event["markets"] == []


@pytest.mark.asyncio
async def test_events_list_forwards_series_ticker(async_client: AsyncClient) -> None:
    """series_ticker query param is forwarded to the Kalshi client call."""
    mock_client = _mock_kalshi_client_events()
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        await async_client.get("/api/catalog/events?series_ticker=KXNBA")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    call_kwargs = mock_client.get_events.call_args.kwargs
    assert call_kwargs["series_ticker"] == "KXNBA"


@pytest.mark.asyncio
async def test_events_list_forwards_status_and_limit(async_client: AsyncClient) -> None:
    """status and limit query params are forwarded to the Kalshi client call."""
    mock_client = _mock_kalshi_client_events()
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        await async_client.get("/api/catalog/events?status=open&limit=50")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    kw = mock_client.get_events.call_args.kwargs
    assert kw["status"] == "open"
    assert kw["limit"] == 50


@pytest.mark.asyncio
async def test_events_list_forwards_cursor(async_client: AsyncClient) -> None:
    """cursor query param is forwarded to the Kalshi client call."""
    mock_client = _mock_kalshi_client_events()
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        await async_client.get("/api/catalog/events?cursor=abc123")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert mock_client.get_events.call_args.kwargs["cursor"] == "abc123"


@pytest.mark.asyncio
async def test_events_list_502_on_http_error(async_client: AsyncClient) -> None:
    """Returns 502 with status=upstream_failure when Kalshi returns 4xx/5xx."""
    mock_client = MagicMock(spec=KalshiRestClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_client.get_events = AsyncMock(
        side_effect=httpx.HTTPStatusError("err", request=MagicMock(), response=mock_resp)
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["events"] == []


@pytest.mark.asyncio
async def test_events_list_502_on_request_error(async_client: AsyncClient) -> None:
    """Returns 502 when the Kalshi request fails at the network level."""
    mock_client = MagicMock(spec=KalshiRestClient)
    mock_client.get_events = AsyncMock(
        side_effect=httpx.ConnectError("timeout")
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    assert response.json()["status"] == "upstream_failure"


# ---------------------------------------------------------------------------
# GET /api/catalog/events/{ticker} — detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_detail_success_with_nested_markets(async_client: AsyncClient) -> None:
    """Returns status=success with the event and its nested markets."""
    mock_client = _mock_kalshi_client_events()
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/events/KXNBA-2026-03-28")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["event"] is not None
    assert data["event"]["event_ticker"] == "KXNBA-2026-03-28"
    markets = data["event"]["markets"]
    assert len(markets) == 1
    assert markets[0]["ticker"] == "KXNBA-2026-03-28-MIA"


@pytest.mark.asyncio
async def test_event_detail_404(async_client: AsyncClient) -> None:
    """Returns 404 with status=not_found when Kalshi responds HTTP 404."""
    mock_client = MagicMock(spec=KalshiRestClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_client.get_event = AsyncMock(
        side_effect=httpx.HTTPStatusError("not found", request=MagicMock(), response=mock_resp)
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/events/DOESNOTEXIST")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "not_found"
    assert data["event"] is None


@pytest.mark.asyncio
async def test_event_detail_502_on_http_error(async_client: AsyncClient) -> None:
    """Returns 502 on non-404 upstream HTTP errors."""
    mock_client = MagicMock(spec=KalshiRestClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_client.get_event = AsyncMock(
        side_effect=httpx.HTTPStatusError("err", request=MagicMock(), response=mock_resp)
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/events/KXNBA-2026-03-28")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    assert response.json()["status"] == "upstream_failure"


@pytest.mark.asyncio
async def test_event_detail_502_on_request_error(async_client: AsyncClient) -> None:
    """Returns 502 on network-level errors for event detail."""
    mock_client = MagicMock(spec=KalshiRestClient)
    mock_client.get_event = AsyncMock(side_effect=httpx.ConnectError("timeout"))
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/events/KXNBA-2026-03-28")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    assert response.json()["status"] == "upstream_failure"
