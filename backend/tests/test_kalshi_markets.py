"""
Tests for GET /api/kalshi/markets.

All tests mock KalshiRestClient via FastAPI dependency overrides so that
no real keys, network connections, or upstream calls are needed.

Key assertions:
- The route returns the normalized internal contract (MarketDTO fields only).
- Raw upstream pricing/volume/trading fields do NOT leak into the response.
- The route handles upstream HTTP errors gracefully (502).
- The route handles network errors gracefully (502).
- Query parameters are forwarded correctly to the client method.
- An empty markets list is valid when Kalshi returns none.
- The cursor is forwarded from upstream and absent when upstream returns empty/null.
"""

from unittest.mock import AsyncMock, MagicMock, call

import httpx
import pytest
from httpx import AsyncClient

from app.dependencies import get_kalshi_client
from app.main import app
from app.services.kalshi.rest_client import KalshiRestClient

# Fields that must NOT appear anywhere in a market object (raw upstream leakage).
_FORBIDDEN_MARKET_FIELDS = {
    "yes_bid_dollars",
    "yes_ask_dollars",
    "no_bid_dollars",
    "no_ask_dollars",
    "last_price_dollars",
    "volume_fp",
    "volume_24h_fp",
    "open_interest_fp",
    "notional_value_dollars",
    "rules_primary",
    "rules_secondary",
    "price_ranges",
    "mve_selected_legs",
}

# Fields that must always be present on a successful response wrapper.
_REQUIRED_RESPONSE_FIELDS = {"status", "message", "markets"}

_SAMPLE_UPSTREAM = {
    "markets": [
        {
            "ticker": "KXBTC-24MAR-T25000",
            "event_ticker": "KXBTC-24MAR",
            "title": "Will Bitcoin be above $25,000?",
            "subtitle": "Bitcoin vs USD",
            "status": "open",
            "close_time": "2024-03-01T00:00:00Z",
            # Raw fields that must not leak through:
            "yes_bid_dollars": "0.5600",
            "yes_ask_dollars": "0.5800",
            "volume_fp": "10.00",
            "rules_primary": "Settlement rules...",
        },
        {
            "ticker": "KXBTC-24MAR-T30000",
            "event_ticker": "KXBTC-24MAR",
            "title": "Will Bitcoin be above $30,000?",
            "subtitle": None,
            "status": "open",
            "close_time": "2024-03-01T00:00:00Z",
        },
    ],
    "cursor": "next-page-token",
}

_SAMPLE_UPSTREAM_EMPTY = {"markets": [], "cursor": ""}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(*, markets_result: dict | None = None) -> MagicMock:
    """Return a MagicMock KalshiRestClient with get_markets pre-configured."""
    client = MagicMock(spec=KalshiRestClient)
    client.is_configured.return_value = True
    client.get_markets = AsyncMock(
        return_value=markets_result if markets_result is not None else _SAMPLE_UPSTREAM
    )
    return client


def _assert_no_raw_fields(market: dict) -> None:
    for field in _FORBIDDEN_MARKET_FIELDS:
        assert field not in market, f"Market DTO must not contain raw field {field!r}"


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_markets_success_shape(async_client: AsyncClient) -> None:
    """Returns 200 with correct wrapper shape and normalized market DTOs."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()

    for field in _REQUIRED_RESPONSE_FIELDS:
        assert field in data, f"Response missing required field {field!r}"

    assert data["status"] == "success"
    assert "Kalshi markets retrieved" in data["message"]
    assert isinstance(data["markets"], list)
    assert len(data["markets"]) == 2


@pytest.mark.asyncio
async def test_kalshi_markets_dto_fields_present(async_client: AsyncClient) -> None:
    """Market DTOs contain exactly the expected discovery fields."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    market = response.json()["markets"][0]
    assert market["ticker"] == "KXBTC-24MAR-T25000"
    assert market["event_ticker"] == "KXBTC-24MAR"
    assert market["title"] == "Will Bitcoin be above $25,000?"
    assert market["subtitle"] == "Bitcoin vs USD"
    assert market["status"] == "open"
    assert market["close_time"] is not None


@pytest.mark.asyncio
async def test_kalshi_markets_no_raw_fields_leaked(async_client: AsyncClient) -> None:
    """Raw upstream pricing and trading fields must not appear in any market DTO."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    for market in response.json()["markets"]:
        _assert_no_raw_fields(market)


@pytest.mark.asyncio
async def test_kalshi_markets_cursor_forwarded(async_client: AsyncClient) -> None:
    """Upstream pagination cursor is included in the response when present."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.json()["cursor"] == "next-page-token"


@pytest.mark.asyncio
async def test_kalshi_markets_empty_upstream(async_client: AsyncClient) -> None:
    """An empty markets list from upstream is valid and returns 200."""
    mock = _mock_client(markets_result=_SAMPLE_UPSTREAM_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["markets"] == []
    assert data["cursor"] is None


@pytest.mark.asyncio
async def test_kalshi_markets_null_subtitle_allowed(async_client: AsyncClient) -> None:
    """Optional DTO fields (subtitle) may be null without error."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    second_market = response.json()["markets"][1]
    assert second_market["ticker"] == "KXBTC-24MAR-T30000"
    assert second_market["subtitle"] is None


# ---------------------------------------------------------------------------
# Query parameter forwarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_markets_status_param_forwarded(async_client: AsyncClient) -> None:
    """status query param is forwarded to the client method."""
    mock = _mock_client(markets_result=_SAMPLE_UPSTREAM_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get("/api/kalshi/markets?status=open")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    mock.get_markets.assert_called_once_with(status="open", limit=100, cursor=None)


@pytest.mark.asyncio
async def test_kalshi_markets_limit_and_cursor_forwarded(async_client: AsyncClient) -> None:
    """limit and cursor query params are forwarded to the client method."""
    mock = _mock_client(markets_result=_SAMPLE_UPSTREAM_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get("/api/kalshi/markets?limit=10&cursor=abc123")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    mock.get_markets.assert_called_once_with(status=None, limit=10, cursor="abc123")


@pytest.mark.asyncio
async def test_kalshi_markets_limit_below_min_rejected(async_client: AsyncClient) -> None:
    """limit=0 violates ge=1 constraint and returns 422."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets?limit=0")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_kalshi_markets_limit_above_max_rejected(async_client: AsyncClient) -> None:
    """limit=1001 violates le=1000 constraint and returns 422."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets?limit=1001")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Upstream error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_markets_upstream_http_error(async_client: AsyncClient) -> None:
    """Returns 502 with upstream_failure when Kalshi responds with an HTTP error."""
    mock = MagicMock(spec=KalshiRestClient)
    mock.is_configured.return_value = True
    http_response = MagicMock()
    http_response.status_code = 500
    mock.get_markets = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Internal Server Error",
            request=MagicMock(),
            response=http_response,
        )
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["markets"] == []
    assert data["cursor"] is None


@pytest.mark.asyncio
async def test_kalshi_markets_network_error(async_client: AsyncClient) -> None:
    """Returns 502 with upstream_failure when the network call fails."""
    mock = MagicMock(spec=KalshiRestClient)
    mock.is_configured.return_value = True
    mock.get_markets = AsyncMock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["markets"] == []
