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
# Price/volume/interest fields ARE now part of MarketDTO (by design) and must not
# be listed here.  Fields excluded from the browse DTO remain forbidden.
_FORBIDDEN_MARKET_FIELDS = {
    "no_bid_dollars",           # not in browse DTO (yes-side sufficient for quick eval)
    "no_ask_dollars",           # not in browse DTO
    "notional_value_dollars",   # detail-view only (MarketDetailDTO)
    "rules_primary",            # detail-view only
    "rules_secondary",          # detail-view only
    "price_ranges",             # complex structure, not in any browse DTO
    "mve_selected_legs",        # complex multivariate structure, not in browse DTO
    "liquidity_dollars",        # omitted from the normalized browse DTO
}

# Fields that must always be present on a successful response wrapper.
_REQUIRED_RESPONSE_FIELDS = {"status", "message", "markets"}

_SAMPLE_UPSTREAM = {
    "markets": [
        {
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
            "notional_value_dollars": "1.0000",
        },
        {
            "ticker": "KXBTC-24MAR-T30000",
            "event_ticker": "KXBTC-24MAR",
            "market_type": "binary",
            "yes_sub_title": None,
            "no_sub_title": None,
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
    """Market DTOs contain the expected browse fields."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    market = response.json()["markets"][0]
    assert market["ticker"] == "KXBTC-24MAR-T25000"
    assert market["event_ticker"] == "KXBTC-24MAR"
    assert market["market_type"] == "binary"
    assert market["yes_sub_title"] == "Above $25,000"
    assert market["no_sub_title"] == "At or below $25,000"
    assert market["title"] == "Will Bitcoin be above $25,000?"
    assert market["subtitle"] == "Bitcoin vs USD"
    assert market["status"] == "open"
    assert market["open_time"] is not None
    assert market["close_time"] is not None


@pytest.mark.asyncio
async def test_kalshi_markets_enriched_price_fields(async_client: AsyncClient) -> None:
    """Price, volume, and open-interest fields are correctly mapped into MarketDTO."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    market = response.json()["markets"][0]
    assert market["yes_bid_dollars"] == "0.5600"
    assert market["yes_ask_dollars"] == "0.5800"
    assert market["last_price_dollars"] == "0.5700"
    assert market["volume_fp"] == "10.00"
    assert market["volume_24h_fp"] == "3.00"
    assert market["open_interest_fp"] == "15.00"


@pytest.mark.asyncio
async def test_kalshi_markets_missing_price_fields_default_none(async_client: AsyncClient) -> None:
    """Price/volume fields default to None when upstream omits them."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    # Second market in fixture has no price/volume fields
    market = response.json()["markets"][1]
    assert market["ticker"] == "KXBTC-24MAR-T30000"
    assert market["yes_bid_dollars"] is None
    assert market["last_price_dollars"] is None
    assert market["volume_fp"] is None
    assert market["open_interest_fp"] is None


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
