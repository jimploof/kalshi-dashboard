"""
Tests for GET /api/catalog/markets/{ticker}.

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

_RAW_MARKET_FULL = {
    "market": {
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
        # MarketDetailDTO-specific fields
        "previous_yes_bid_dollars": "0.50",
        "previous_yes_ask_dollars": "0.52",
        "previous_price_dollars": "0.51",
        "notional_value_dollars": "1.00",
        "settlement_value_dollars": None,
        "settlement_ts": None,
        "strike_type": "greater",
        "floor_strike": None,
        "cap_strike": None,
        "rules_primary": "Market settles YES if Miami wins.",
        "rules_secondary": None,
        "is_provisional": False,
        "fractional_trading_enabled": False,
    }
}


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_detail_success_shape(async_client: AsyncClient) -> None:
    """Returns 200 with status=success and full MarketDetailDTO fields."""
    mock_client = MagicMock(spec=KalshiRestClient)
    mock_client.get_market = AsyncMock(return_value=_RAW_MARKET_FULL)
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/markets/KXNBA-2026-03-28-MIA")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["market"] is not None
    market = data["market"]
    assert market["ticker"] == "KXNBA-2026-03-28-MIA"
    assert market["event_ticker"] == "KXNBA-2026-03-28"
    # detail-only fields present
    assert market["previous_yes_bid_dollars"] == "0.50"
    assert market["strike_type"] == "greater"
    assert market["rules_primary"] == "Market settles YES if Miami wins."
    assert market["is_provisional"] is False


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_detail_404(async_client: AsyncClient) -> None:
    """Returns 404 with status=not_found when Kalshi responds HTTP 404."""
    mock_client = MagicMock(spec=KalshiRestClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_client.get_market = AsyncMock(
        side_effect=httpx.HTTPStatusError("not found", request=MagicMock(), response=mock_resp)
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/markets/DOESNOTEXIST")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "not_found"
    assert data["market"] is None


# ---------------------------------------------------------------------------
# Upstream failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_detail_502_on_http_error(async_client: AsyncClient) -> None:
    """Returns 502 on non-404 upstream HTTP errors."""
    mock_client = MagicMock(spec=KalshiRestClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_client.get_market = AsyncMock(
        side_effect=httpx.HTTPStatusError("server error", request=MagicMock(), response=mock_resp)
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/markets/KXNBA-2026-03-28-MIA")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["market"] is None


@pytest.mark.asyncio
async def test_market_detail_502_on_request_error(async_client: AsyncClient) -> None:
    """Returns 502 when the Kalshi request fails at the network level."""
    mock_client = MagicMock(spec=KalshiRestClient)
    mock_client.get_market = AsyncMock(side_effect=httpx.ConnectError("timeout"))
    app.dependency_overrides[get_kalshi_client] = lambda: mock_client

    try:
        response = await async_client.get("/api/catalog/markets/KXNBA-2026-03-28-MIA")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    assert response.json()["status"] == "upstream_failure"
