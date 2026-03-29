"""
Tests for GET /api/kalshi/markets/{ticker} (single market detail).

All tests mock KalshiRestClient via FastAPI dependency overrides so that
no real keys, network connections, or upstream calls are needed.

Key assertions:
- Returns 200 with MarketDetailDTO on success.
- MarketDetailDTO includes all browse fields (inherited from MarketDTO) plus
  the detail-only fields (previous prices, settlement, strike, rules).
- Fields explicitly excluded from the detail DTO do not appear:
  no_bid_dollars, no_ask_dollars, liquidity_dollars, price_ranges,
  mve_selected_legs.
- Returns 404 (not_found) when Kalshi responds HTTP 404.
- Returns 502 (upstream_failure) on other HTTP errors.
- Returns 502 (upstream_failure) on network errors.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import AsyncClient

from app.dependencies import get_kalshi_client
from app.main import app
from app.services.kalshi.rest_client import KalshiRestClient

# Fields that must NOT appear in the detail response (explicitly excluded from
# MarketDetailDTO by design because they are not currently needed by the UI).
_FORBIDDEN_DETAIL_FIELDS = {
    "no_bid_dollars",       # not in any DTO
    "no_ask_dollars",       # not in any DTO
    "liquidity_dollars",    # omitted from the normalized DTO
    "price_ranges",         # complex structure, excluded from DTOs
    "mve_selected_legs",    # complex multivariate structure, excluded
    "tick_size",            # omitted from the normalized DTO
    "expiration_time",      # omitted from the normalized DTO
    "response_price_units", # omitted from the normalized DTO
}

# Required fields on a successful MarketDetailDTO.
_REQUIRED_DETAIL_FIELDS = {
    "ticker", "event_ticker", "market_type", "yes_sub_title", "no_sub_title",
    "status", "yes_bid_dollars", "yes_ask_dollars", "last_price_dollars",
    "volume_fp", "volume_24h_fp", "open_interest_fp",
    "previous_yes_bid_dollars", "previous_yes_ask_dollars", "previous_price_dollars",
    "notional_value_dollars", "rules_primary", "rules_secondary",
}

# ---------------------------------------------------------------------------
# Sample upstream payloads
# ---------------------------------------------------------------------------

_SAMPLE_MARKET_RAW = {
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
    # Browse price/volume fields
    "yes_bid_dollars": "0.5600",
    "yes_ask_dollars": "0.5800",
    "last_price_dollars": "0.5700",
    "volume_fp": "250.00",
    "volume_24h_fp": "80.00",
    "open_interest_fp": "420.00",
    # Detail-only fields
    "previous_yes_bid_dollars": "0.5400",
    "previous_yes_ask_dollars": "0.5600",
    "previous_price_dollars": "0.5500",
    "notional_value_dollars": "1.0000",
    "settlement_value_dollars": None,
    "settlement_ts": None,
    "strike_type": "greater",
    "floor_strike": 25000.0,
    "cap_strike": None,
    "rules_primary": "Resolves YES if Bitcoin closes above $25,000.",
    "rules_secondary": "Uses Coinbase BTCUSD spot price at 12:00 UTC.",
    "is_provisional": False,
    "fractional_trading_enabled": True,
    # Fields that should NOT appear in the DTO:
    "no_bid_dollars": "0.4200",
    "no_ask_dollars": "0.4400",
    "liquidity_dollars": "0.0000",
    "price_ranges": [{"start": "0.01", "end": "0.99", "step": "0.01"}],
    "mve_selected_legs": [],
    "tick_size": 1,
    "expiration_time": "2024-03-01T12:00:00Z",
    "response_price_units": "usd_cent",
}

_SAMPLE_UPSTREAM_RESPONSE = {"market": _SAMPLE_MARKET_RAW}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(*, result: dict | None = None, side_effect: Exception | None = None) -> MagicMock:
    client = MagicMock(spec=KalshiRestClient)
    client.is_configured.return_value = True
    if side_effect is not None:
        client.get_market = AsyncMock(side_effect=side_effect)
    else:
        client.get_market = AsyncMock(return_value=result if result is not None else _SAMPLE_UPSTREAM_RESPONSE)
    return client


def _assert_no_forbidden_fields(market: dict) -> None:
    for field in _FORBIDDEN_DETAIL_FIELDS:
        assert field not in market, f"MarketDetailDTO must not contain field {field!r}"


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_market_detail_success_shape(async_client: AsyncClient) -> None:
    """Returns 200 with status=success and a populated market."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets/KXBTC-24MAR-T25000")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "market retrieved" in data["message"]
    assert data["market"] is not None


@pytest.mark.asyncio
async def test_kalshi_market_detail_browse_fields(async_client: AsyncClient) -> None:
    """MarketDetailDTO contains all inherited browse fields from MarketDTO."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets/KXBTC-24MAR-T25000")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    market = response.json()["market"]
    assert market["ticker"] == "KXBTC-24MAR-T25000"
    assert market["event_ticker"] == "KXBTC-24MAR"
    assert market["market_type"] == "binary"
    assert market["yes_sub_title"] == "Above $25,000"
    assert market["no_sub_title"] == "At or below $25,000"
    assert market["status"] == "open"
    assert market["yes_bid_dollars"] == "0.5600"
    assert market["yes_ask_dollars"] == "0.5800"
    assert market["last_price_dollars"] == "0.5700"
    assert market["volume_fp"] == "250.00"
    assert market["volume_24h_fp"] == "80.00"
    assert market["open_interest_fp"] == "420.00"


@pytest.mark.asyncio
async def test_kalshi_market_detail_price_movement_fields(async_client: AsyncClient) -> None:
    """MarketDetailDTO includes previous-price and notional fields for order-entry context."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets/KXBTC-24MAR-T25000")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    market = response.json()["market"]
    assert market["previous_yes_bid_dollars"] == "0.5400"
    assert market["previous_yes_ask_dollars"] == "0.5600"
    assert market["previous_price_dollars"] == "0.5500"
    assert market["notional_value_dollars"] == "1.0000"


@pytest.mark.asyncio
async def test_kalshi_market_detail_rules_and_strike(async_client: AsyncClient) -> None:
    """MarketDetailDTO includes rules and strike fields for market inspection."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets/KXBTC-24MAR-T25000")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    market = response.json()["market"]
    assert market["rules_primary"] == "Resolves YES if Bitcoin closes above $25,000."
    assert market["rules_secondary"] == "Uses Coinbase BTCUSD spot price at 12:00 UTC."
    assert market["strike_type"] == "greater"
    assert market["floor_strike"] == 25000.0
    assert market["cap_strike"] is None
    assert market["is_provisional"] is False
    assert market["fractional_trading_enabled"] is True


@pytest.mark.asyncio
async def test_kalshi_market_detail_settlement_fields_null_for_open(async_client: AsyncClient) -> None:
    """Settlement fields are None for an open market (only populated after determination)."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets/KXBTC-24MAR-T25000")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    market = response.json()["market"]
    assert market["settlement_value_dollars"] is None
    assert market["settlement_ts"] is None


@pytest.mark.asyncio
async def test_kalshi_market_detail_no_forbidden_fields(async_client: AsyncClient) -> None:
    """Explicitly excluded upstream fields must not appear in the detail DTO."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets/KXBTC-24MAR-T25000")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    _assert_no_forbidden_fields(response.json()["market"])


@pytest.mark.asyncio
async def test_kalshi_market_detail_ticker_path_forwarded(async_client: AsyncClient) -> None:
    """The ticker path parameter is forwarded to the client method."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get("/api/kalshi/markets/KXBTC-24MAR-T25000")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    mock.get_market.assert_called_once_with("KXBTC-24MAR-T25000")


@pytest.mark.asyncio
async def test_kalshi_market_detail_optional_fields_default_none(async_client: AsyncClient) -> None:
    """Optional fields default to None when the upstream omits them."""
    minimal = {
        "market": {
            "ticker": "KXBTC-24MAR-T25000",
            "event_ticker": "KXBTC-24MAR",
        }
    }
    mock = _mock_client(result=minimal)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets/KXBTC-24MAR-T25000")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    market = response.json()["market"]
    assert market["ticker"] == "KXBTC-24MAR-T25000"
    assert market["market_type"] is None
    assert market["yes_bid_dollars"] is None
    assert market["volume_fp"] is None
    assert market["rules_primary"] is None
    assert market["settlement_value_dollars"] is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_market_detail_not_found(async_client: AsyncClient) -> None:
    """Returns 404 with not_found status when Kalshi responds HTTP 404."""
    http_response = MagicMock()
    http_response.status_code = 404
    mock = _mock_client(
        side_effect=httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=http_response
        )
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets/NONEXISTENT-TICKER")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "not_found"
    assert data["market"] is None


@pytest.mark.asyncio
async def test_kalshi_market_detail_upstream_http_error(async_client: AsyncClient) -> None:
    """Returns 502 with upstream_failure on non-404 upstream HTTP errors."""
    http_response = MagicMock()
    http_response.status_code = 503
    mock = _mock_client(
        side_effect=httpx.HTTPStatusError(
            "Service Unavailable", request=MagicMock(), response=http_response
        )
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets/KXBTC-24MAR-T25000")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["market"] is None


@pytest.mark.asyncio
async def test_kalshi_market_detail_network_error(async_client: AsyncClient) -> None:
    """Returns 502 with upstream_failure on network errors."""
    mock = _mock_client(side_effect=httpx.ConnectError("Connection refused"))
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/markets/KXBTC-24MAR-T25000")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["market"] is None
