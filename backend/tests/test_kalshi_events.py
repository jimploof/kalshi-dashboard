"""
Tests for GET /api/kalshi/events.

All tests mock KalshiRestClient via FastAPI dependency overrides so that
no real keys, network connections, or upstream calls are needed.

Key assertions:
- The route returns the correct normalized EventDTO contract.
- Raw upstream fields (pricing, volume, rules, mve_selected_legs) do NOT leak.
- Nested markets are empty unless with_nested_markets=True was requested.
- Nested markets within events are normalized via the same MarketDTO shape.
- category is present and forwarded from the event object (NOT from series).
- mutually_exclusive is forwarded faithfully.
- sub_title is forwarded faithfully.
- Query params are forwarded correctly to the client method.
- An empty events list is valid when Kalshi returns none.
- The cursor is forwarded from upstream.
- Upstream HTTP errors return 502 with upstream_failure and empty events list.
- Network errors return 502 with upstream_failure and empty events list.
- limit is validated: ge=1, le=200.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import AsyncClient

from app.dependencies import get_kalshi_client
from app.main import app
from app.services.kalshi.rest_client import KalshiRestClient

# Raw fields that must NOT appear on any EventDTO or nested MarketDTO.
# Price/volume/interest fields ARE now part of MarketDTO and must not be listed here.
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
_FORBIDDEN_EVENT_FIELDS = {
    "collateral_return_type",
    "available_on_brokers",
    "product_metadata",
    "strike_period",
    "last_updated_ts",
}

# Fields required on each successful EventDTO.
_REQUIRED_EVENT_FIELDS = {"event_ticker", "markets"}

# ---------------------------------------------------------------------------
# Sample upstream payloads
# ---------------------------------------------------------------------------

_SAMPLE_MARKET = {
    "ticker": "KXBTC-24MAR-T25000",
    "event_ticker": "KXBTC-24MAR",
    "market_type": "binary",
    "yes_sub_title": "Above $25,000",
    "no_sub_title": "At or below $25,000",
    "title": "Will Bitcoin be above $25,000?",
    "subtitle": "Bitcoin vs USD",
    "status": "open",
    "open_time": "2024-02-01T00:00:00Z",
    "close_time": "2024-03-01T00:00:00Z",
    "yes_bid_dollars": "0.5600",
    "yes_ask_dollars": "0.5800",
    "last_price_dollars": "0.5700",
    "volume_fp": "10.00",
    "volume_24h_fp": "3.00",
    "open_interest_fp": "15.00",
    # Fields that must not leak into browse DTO:
    "no_bid_dollars": "0.4200",
    "no_ask_dollars": "0.4400",
    "rules_primary": "Settlement rules...",
    "mve_selected_legs": [],
}

_SAMPLE_UPSTREAM_WITHOUT_MARKETS = {
    "events": [
        {
            "event_ticker": "KXBTC-24MAR",
            "series_ticker": "KXBTC",
            "title": "Bitcoin March 2024",
            "sub_title": "Will Bitcoin cross price thresholds?",
            "category": "crypto",
            "mutually_exclusive": False,
            "available_on_brokers": True,
            "product_metadata": {"some_key": "some_value"},
            "collateral_return_type": "proportional",
            "strike_period": "daily",
            "last_updated_ts": "2024-01-01T00:00:00Z",
            # No 'markets' key — simulates with_nested_markets=False response
        },
        {
            "event_ticker": "KXETH-24MAR",
            "series_ticker": "KXETH",
            "title": "Ethereum March 2024",
            "sub_title": None,
            "category": "crypto",
            "mutually_exclusive": True,
            "last_updated_ts": "2024-01-01T00:00:00Z",
        },
    ],
    "cursor": "next-cursor-token",
}

_SAMPLE_UPSTREAM_WITH_MARKETS = {
    "events": [
        {
            "event_ticker": "KXBTC-24MAR",
            "series_ticker": "KXBTC",
            "title": "Bitcoin March 2024",
            "sub_title": "Will Bitcoin cross price thresholds?",
            "category": "crypto",
            "mutually_exclusive": False,
            "markets": [_SAMPLE_MARKET],
            "last_updated_ts": "2024-01-01T00:00:00Z",
        }
    ],
    "cursor": "",
}

_SAMPLE_UPSTREAM_EMPTY = {"events": [], "cursor": ""}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(*, result: dict) -> MagicMock:
    client = MagicMock(spec=KalshiRestClient)
    client.is_configured.return_value = True
    client.get_events = AsyncMock(return_value=result)
    return client


# ---------------------------------------------------------------------------
# Success path — without nested markets (default)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_events_success_shape(async_client: AsyncClient) -> None:
    """Returns 200 with correct wrapper shape."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_WITHOUT_MARKETS)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "Kalshi events retrieved" in data["message"]
    assert isinstance(data["events"], list)
    assert len(data["events"]) == 2


@pytest.mark.asyncio
async def test_kalshi_events_dto_fields_present(async_client: AsyncClient) -> None:
    """EventDTO contains the expected discovery fields from the documented response."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_WITHOUT_MARKETS)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    event = response.json()["events"][0]
    assert event["event_ticker"] == "KXBTC-24MAR"
    assert event["series_ticker"] == "KXBTC"
    assert event["title"] == "Bitcoin March 2024"
    assert event["sub_title"] == "Will Bitcoin cross price thresholds?"
    assert event["category"] == "crypto"
    assert event["mutually_exclusive"] is False


@pytest.mark.asyncio
async def test_kalshi_events_no_raw_fields_leaked_on_event(async_client: AsyncClient) -> None:
    """Raw upstream event fields must not appear in any EventDTO."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_WITHOUT_MARKETS)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    for event in response.json()["events"]:
        for field in _FORBIDDEN_EVENT_FIELDS:
            assert field not in event, f"EventDTO must not contain raw field {field!r}"


@pytest.mark.asyncio
async def test_kalshi_events_no_nested_markets_by_default(async_client: AsyncClient) -> None:
    """Markets list is empty by default when with_nested_markets is not requested."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_WITHOUT_MARKETS)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    for event in response.json()["events"]:
        assert event["markets"] == [], "markets must be empty when upstream returns no markets"


@pytest.mark.asyncio
async def test_kalshi_events_null_sub_title_allowed(async_client: AsyncClient) -> None:
    """Optional sub_title field may be null without error."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_WITHOUT_MARKETS)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    second_event = response.json()["events"][1]
    assert second_event["event_ticker"] == "KXETH-24MAR"
    assert second_event["sub_title"] is None


@pytest.mark.asyncio
async def test_kalshi_events_cursor_forwarded(async_client: AsyncClient) -> None:
    """Pagination cursor is forwarded from upstream response."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_WITHOUT_MARKETS)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.json()["cursor"] == "next-cursor-token"


@pytest.mark.asyncio
async def test_kalshi_events_empty_cursor_becomes_none(async_client: AsyncClient) -> None:
    """An empty string cursor from upstream is normalized to null."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_WITH_MARKETS)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events?with_nested_markets=true")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.json()["cursor"] is None


@pytest.mark.asyncio
async def test_kalshi_events_empty_upstream(async_client: AsyncClient) -> None:
    """An empty events list from upstream is valid and returns 200."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["events"] == []
    assert data["cursor"] is None


# ---------------------------------------------------------------------------
# Nested markets — with_nested_markets=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_events_with_nested_markets_populated(async_client: AsyncClient) -> None:
    """When upstream returns markets inside an event, they are normalized via MarketDTO."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_WITH_MARKETS)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events?with_nested_markets=true")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    event = response.json()["events"][0]
    assert len(event["markets"]) == 1
    market = event["markets"][0]
    assert market["ticker"] == "KXBTC-24MAR-T25000"
    assert market["event_ticker"] == "KXBTC-24MAR"
    assert market["title"] == "Will Bitcoin be above $25,000?"
    assert market["status"] == "open"


@pytest.mark.asyncio
async def test_kalshi_events_nested_markets_no_raw_fields(async_client: AsyncClient) -> None:
    """Raw upstream pricing fields must not appear in nested market DTOs."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_WITH_MARKETS)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events?with_nested_markets=true")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    for event in response.json()["events"]:
        for market in event["markets"]:
            for field in _FORBIDDEN_MARKET_FIELDS:
                assert field not in market, f"Nested MarketDTO must not contain raw field {field!r}"


# ---------------------------------------------------------------------------
# Query parameter forwarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_events_default_params_forwarded(async_client: AsyncClient) -> None:
    """Default query params are forwarded correctly to the client method."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get("/api/kalshi/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    mock.get_events.assert_called_once_with(
        series_ticker=None,
        status=None,
        limit=100,
        cursor=None,
        with_nested_markets=False,
        min_close_ts=None,
        min_updated_ts=None,
    )


@pytest.mark.asyncio
async def test_kalshi_events_explicit_params_forwarded(async_client: AsyncClient) -> None:
    """Explicit base query params are forwarded correctly to the client method."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get(
            "/api/kalshi/events?series_ticker=KXBTC&status=open&limit=50&cursor=abc&with_nested_markets=true"
        )
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    mock.get_events.assert_called_once_with(
        series_ticker="KXBTC",
        status="open",
        limit=50,
        cursor="abc",
        with_nested_markets=True,
        min_close_ts=None,
        min_updated_ts=None,
    )


@pytest.mark.asyncio
async def test_kalshi_events_min_close_ts_forwarded(async_client: AsyncClient) -> None:
    """min_close_ts query param is forwarded as int to the client method."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get("/api/kalshi/events?min_close_ts=1711929600")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    mock.get_events.assert_called_once_with(
        series_ticker=None,
        status=None,
        limit=100,
        cursor=None,
        with_nested_markets=False,
        min_close_ts=1711929600,
        min_updated_ts=None,
    )


@pytest.mark.asyncio
async def test_kalshi_events_min_updated_ts_forwarded(async_client: AsyncClient) -> None:
    """min_updated_ts query param is forwarded as int to the client method."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get("/api/kalshi/events?min_updated_ts=1711843200")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    mock.get_events.assert_called_once_with(
        series_ticker=None,
        status=None,
        limit=100,
        cursor=None,
        with_nested_markets=False,
        min_close_ts=None,
        min_updated_ts=1711843200,
    )


@pytest.mark.asyncio
async def test_kalshi_events_limit_below_min_rejected(async_client: AsyncClient) -> None:
    """limit=0 violates ge=1 constraint and returns 422."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events?limit=0")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_kalshi_events_limit_above_max_rejected(async_client: AsyncClient) -> None:
    """limit=201 violates le=200 constraint (Kalshi max) and returns 422."""
    mock = _mock_client(result=_SAMPLE_UPSTREAM_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events?limit=201")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Upstream error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_events_upstream_http_error(async_client: AsyncClient) -> None:
    """Returns 502 with upstream_failure when Kalshi responds with an HTTP error."""
    mock = MagicMock(spec=KalshiRestClient)
    mock.is_configured.return_value = True
    http_response = MagicMock()
    http_response.status_code = 500
    mock.get_events = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Internal Server Error",
            request=MagicMock(),
            response=http_response,
        )
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["events"] == []
    assert data["cursor"] is None


@pytest.mark.asyncio
async def test_kalshi_events_network_error(async_client: AsyncClient) -> None:
    """Returns 502 with upstream_failure when the network call fails."""
    mock = MagicMock(spec=KalshiRestClient)
    mock.is_configured.return_value = True
    mock.get_events = AsyncMock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/events")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["events"] == []
