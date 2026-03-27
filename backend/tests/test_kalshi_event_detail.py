"""
Tests for GET /api/kalshi/events/{ticker} (single event detail).

All tests mock KalshiRestClient via FastAPI dependency overrides.

Key assertions:
- Returns 200 with EventDTO on success (with nested markets from event.markets).
- The deprecated top-level ``markets`` field is NOT used; only event.markets.
- Raw upstream fields do not leak into EventDTO or nested MarketDTOs.
- Returns 404 (not_found) when Kalshi responds HTTP 404.
- Returns 502 (upstream_failure) on other HTTP errors.
- Returns 502 (upstream_failure) on network errors.
- with_nested_markets=True is always forwarded to the client.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import AsyncClient

from app.dependencies import get_kalshi_client
from app.main import app
from app.services.kalshi.rest_client import KalshiRestClient

_FORBIDDEN_EVENT_FIELDS = {
    "collateral_return_type",
    "available_on_brokers",
    "product_metadata",
    "strike_period",
    "last_updated_ts",
}
_FORBIDDEN_MARKET_FIELDS = {
    "no_bid_dollars",           # not in browse DTO
    "no_ask_dollars",           # not in browse DTO
    "notional_value_dollars",   # detail-only (MarketDetailDTO)
    "rules_primary",            # detail-only
    "rules_secondary",          # detail-only
    "price_ranges",             # complex, not in any browse DTO
    "mve_selected_legs",        # complex, not in browse DTO
    "liquidity_dollars",        # deprecated by Kalshi; always "0.0000"
}

# ---------------------------------------------------------------------------
# Sample upstream payload
# ---------------------------------------------------------------------------

_SAMPLE_MARKET = {
    "ticker": "KXBTC-24MAR-T25000",
    "event_ticker": "KXBTC-24MAR",
    "market_type": "binary",
    "yes_sub_title": "Above $25k",
    "no_sub_title": "At or below $25k",
    "title": "Will Bitcoin exceed $25k?",
    "subtitle": "Bitcoin threshold",
    "status": "open",
    "open_time": "2024-02-01T00:00:00Z",
    "close_time": "2024-03-01T00:00:00Z",
    "yes_bid_dollars": "0.5600",
    "yes_ask_dollars": "0.5800",
    "last_price_dollars": "0.5700",
    "volume_fp": "10.00",
    "volume_24h_fp": "3.00",
    "open_interest_fp": "15.00",
    # Fields that must not appear in browse DTO:
    "no_bid_dollars": "0.4200",
    "no_ask_dollars": "0.4400",
    "rules_primary": "Settlement rules...",
    "mve_selected_legs": [],
}

_SAMPLE_EVENT_RESPONSE = {
    "event": {
        "event_ticker": "KXBTC-24MAR",
        "series_ticker": "KXBTC",
        "title": "Bitcoin March 2024",
        "sub_title": "Bitcoin threshold markets",
        "category": "crypto",
        "mutually_exclusive": False,
        "available_on_brokers": True,
        "product_metadata": {},
        "collateral_return_type": "proportional",
        "strike_period": "daily",
        "last_updated_ts": "2024-01-01T00:00:00Z",
        "markets": [_SAMPLE_MARKET],
    },
    # Deprecated top-level markets field — must NOT be used in normalisation.
    "markets": [
        {
            "ticker": "DEPRECATED-FIELD",
            "event_ticker": "KXBTC-24MAR",
            "title": "Should not appear",
            "subtitle": None,
            "status": "open",
            "close_time": "2024-03-01T00:00:00Z",
        }
    ],
}

_SAMPLE_EVENT_NO_MARKETS = {
    "event": {
        "event_ticker": "KXBTC-24MAR",
        "series_ticker": "KXBTC",
        "title": "Bitcoin March 2024",
        "sub_title": None,
        "category": "crypto",
        "mutually_exclusive": True,
    },
    "markets": [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(*, result: dict) -> MagicMock:
    client = MagicMock(spec=KalshiRestClient)
    client.is_configured.return_value = True
    client.get_event = AsyncMock(return_value=result)
    return client


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_event_detail_success_shape(async_client: AsyncClient) -> None:
    """Returns 200 with status=success and a populated event."""
    mock = _mock_client(result=_SAMPLE_EVENT_RESPONSE)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events/KXBTC-24MAR")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "event retrieved" in data["message"]
    assert data["event"] is not None


@pytest.mark.asyncio
async def test_kalshi_event_detail_dto_fields(async_client: AsyncClient) -> None:
    """EventDTO fields are correctly populated from event object."""
    mock = _mock_client(result=_SAMPLE_EVENT_RESPONSE)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events/KXBTC-24MAR")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    event = response.json()["event"]
    assert event["event_ticker"] == "KXBTC-24MAR"
    assert event["series_ticker"] == "KXBTC"
    assert event["title"] == "Bitcoin March 2024"
    assert event["sub_title"] == "Bitcoin threshold markets"
    assert event["category"] == "crypto"
    assert event["mutually_exclusive"] is False


@pytest.mark.asyncio
async def test_kalshi_event_detail_uses_nested_markets_not_deprecated(async_client: AsyncClient) -> None:
    """Nested markets come from event.markets, not the deprecated top-level markets field."""
    mock = _mock_client(result=_SAMPLE_EVENT_RESPONSE)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events/KXBTC-24MAR")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    markets = response.json()["event"]["markets"]
    assert len(markets) == 1
    assert markets[0]["ticker"] == "KXBTC-24MAR-T25000", (
        "Should use event.markets, not deprecated top-level markets field"
    )


@pytest.mark.asyncio
async def test_kalshi_event_detail_nested_market_dto_fields(async_client: AsyncClient) -> None:
    """Nested MarketDTO fields are correctly normalised."""
    mock = _mock_client(result=_SAMPLE_EVENT_RESPONSE)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events/KXBTC-24MAR")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    market = response.json()["event"]["markets"][0]
    assert market["ticker"] == "KXBTC-24MAR-T25000"
    assert market["event_ticker"] == "KXBTC-24MAR"
    assert market["title"] == "Will Bitcoin exceed $25k?"
    assert market["status"] == "open"


@pytest.mark.asyncio
async def test_kalshi_event_detail_no_raw_event_fields(async_client: AsyncClient) -> None:
    """Raw upstream event fields must not appear in the EventDTO."""
    mock = _mock_client(result=_SAMPLE_EVENT_RESPONSE)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events/KXBTC-24MAR")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    event = response.json()["event"]
    for field in _FORBIDDEN_EVENT_FIELDS:
        assert field not in event


@pytest.mark.asyncio
async def test_kalshi_event_detail_no_raw_market_fields(async_client: AsyncClient) -> None:
    """Raw upstream pricing fields must not appear in nested MarketDTOs."""
    mock = _mock_client(result=_SAMPLE_EVENT_RESPONSE)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events/KXBTC-24MAR")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    for market in response.json()["event"]["markets"]:
        for field in _FORBIDDEN_MARKET_FIELDS:
            assert field not in market


@pytest.mark.asyncio
async def test_kalshi_event_detail_empty_markets(async_client: AsyncClient) -> None:
    """An event with no markets is valid — markets list is empty."""
    mock = _mock_client(result=_SAMPLE_EVENT_NO_MARKETS)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events/KXBTC-24MAR")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    assert response.json()["event"]["markets"] == []


@pytest.mark.asyncio
async def test_kalshi_event_detail_always_requests_nested_markets(async_client: AsyncClient) -> None:
    """with_nested_markets=True is always forwarded to the client method."""
    mock = _mock_client(result=_SAMPLE_EVENT_RESPONSE)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get("/api/kalshi/events/KXBTC-24MAR")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    mock.get_event.assert_called_once_with("KXBTC-24MAR", with_nested_markets=True)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_event_detail_not_found(async_client: AsyncClient) -> None:
    """Returns 404 with not_found when Kalshi responds HTTP 404."""
    mock = MagicMock(spec=KalshiRestClient)
    mock.is_configured.return_value = True
    http_response = MagicMock()
    http_response.status_code = 404
    mock.get_event = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=http_response
        )
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events/UNKNOWN-TICKER")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "not_found"
    assert data["event"] is None


@pytest.mark.asyncio
async def test_kalshi_event_detail_upstream_http_error(async_client: AsyncClient) -> None:
    """Returns 502 with upstream_failure for non-404 HTTP errors."""
    mock = MagicMock(spec=KalshiRestClient)
    mock.is_configured.return_value = True
    http_response = MagicMock()
    http_response.status_code = 503
    mock.get_event = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Service Unavailable", request=MagicMock(), response=http_response
        )
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events/KXBTC-24MAR")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["event"] is None


@pytest.mark.asyncio
async def test_kalshi_event_detail_network_error(async_client: AsyncClient) -> None:
    """Returns 502 with upstream_failure when the network call fails."""
    mock = MagicMock(spec=KalshiRestClient)
    mock.is_configured.return_value = True
    mock.get_event = AsyncMock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events/KXBTC-24MAR")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["event"] is None
