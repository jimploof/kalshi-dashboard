"""
Tests for event outcomes and event candlestick endpoints.

  GET /api/market/event/{event_ticker}/outcomes
  GET /api/market/event/{event_ticker}/candlesticks

All tests mock the KalshiRestClient via FastAPI dependency overrides.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import AsyncClient

from app.dependencies import get_kalshi_client
from app.main import app
from app.services.kalshi.rest_client import KalshiRestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client() -> MagicMock:
    client = MagicMock(spec=KalshiRestClient)
    client.is_configured.return_value = True
    return client


_SAMPLE_EVENT = {
    "event": {
        "event_ticker": "NBA-GSWAR-BOS-2025",
        "title": "Warriors vs Celtics",
        "mutually_exclusive": True,
        "markets": [
            {
                "ticker": "NBA-GSWAR-BOS-2025-GSWAR",
                "yes_sub_title": "Warriors",
                "last_price_dollars": "0.35",
                "status": "open",
            },
            {
                "ticker": "NBA-GSWAR-BOS-2025-BOS",
                "yes_sub_title": "Celtics",
                "last_price_dollars": "0.65",
                "status": "open",
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# GET /api/market/event/{event_ticker}/outcomes — success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_outcomes_success(async_client: AsyncClient) -> None:
    """Returns outcomes sorted by price descending."""
    mock = _mock_client()
    mock.get_event = AsyncMock(return_value=_SAMPLE_EVENT)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get(
            "/api/market/event/NBA-GSWAR-BOS-2025/outcomes",
        )
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["event_ticker"] == "NBA-GSWAR-BOS-2025"
    assert data["title"] == "Warriors vs Celtics"
    assert data["mutually_exclusive"] is True
    assert len(data["outcomes"]) == 2
    # Sorted by price descending — Celtics (0.65) first.
    assert data["outcomes"][0]["ticker"] == "NBA-GSWAR-BOS-2025-BOS"
    assert data["outcomes"][0]["yes_sub_title"] == "Celtics"
    assert data["outcomes"][1]["ticker"] == "NBA-GSWAR-BOS-2025-GSWAR"
    assert data["outcomes"][1]["yes_sub_title"] == "Warriors"


@pytest.mark.asyncio
async def test_event_outcomes_not_found(async_client: AsyncClient) -> None:
    """Returns not_found when Kalshi returns 404."""
    mock = _mock_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock.get_event = AsyncMock(
        side_effect=httpx.HTTPStatusError("not found", request=MagicMock(), response=mock_resp),
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get(
            "/api/market/event/FAKE-EVENT/outcomes",
        )
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_found"
    assert data["outcomes"] == []


@pytest.mark.asyncio
async def test_event_outcomes_upstream_failure(async_client: AsyncClient) -> None:
    """Returns upstream_failure on network error."""
    mock = _mock_client()
    mock.get_event = AsyncMock(
        side_effect=httpx.RequestError("connection refused"),
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get(
            "/api/market/event/BROKEN/outcomes",
        )
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "upstream_failure"


@pytest.mark.asyncio
async def test_event_outcomes_no_raw_leaks(async_client: AsyncClient) -> None:
    """DTO must not leak raw upstream fields beyond the schema."""
    mock = _mock_client()
    mock.get_event = AsyncMock(return_value=_SAMPLE_EVENT)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get(
            "/api/market/event/NBA-GSWAR-BOS-2025/outcomes",
        )
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    data = response.json()
    allowed_outcome_fields = {"ticker", "yes_sub_title", "last_price_dollars", "status"}
    for outcome in data["outcomes"]:
        assert set(outcome.keys()) <= allowed_outcome_fields


# ---------------------------------------------------------------------------
# GET /api/market/event/{event_ticker}/candlesticks — success
# ---------------------------------------------------------------------------


_SAMPLE_CANDLES = {
    "candlesticks": [
        {
            "end_period_ts": 1711400000,
            "price": {
                "open_dollars": "0.50",
                "high_dollars": "0.55",
                "low_dollars": "0.48",
                "close_dollars": "0.52",
            },
            "volume_fp": "120",
        },
        {
            "end_period_ts": 1711400060,
            "price": {
                "open_dollars": "0.52",
                "high_dollars": "0.58",
                "low_dollars": "0.51",
                "close_dollars": "0.56",
            },
            "volume_fp": "85",
        },
    ],
}


@pytest.mark.asyncio
async def test_event_candlesticks_success(async_client: AsyncClient) -> None:
    """Fetches candlesticks for multiple tickers and normalises to cents."""
    mock = _mock_client()
    mock.get_candlesticks = AsyncMock(return_value=_SAMPLE_CANDLES)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get(
            "/api/market/event/NBA-GSWAR-BOS-2025/candlesticks",
            params={
                "tickers": "NBA-GSWAR-BOS-2025-GSWAR,NBA-GSWAR-BOS-2025-BOS",
                "start_ts": 1711400000,
                "end_ts": 1711500000,
                "period_interval": 1,
            },
        )
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["event_ticker"] == "NBA-GSWAR-BOS-2025"
    assert len(data["outcomes"]) == 2

    # Each outcome should have 2 candles with cent-normalised prices.
    for outcome in data["outcomes"]:
        assert len(outcome["candlesticks"]) == 2
        first = outcome["candlesticks"][0]
        assert first["open"] == 50
        assert first["high"] == 55
        assert first["low"] == 48
        assert first["close"] == 52
        assert first["volume"] == 120


@pytest.mark.asyncio
async def test_event_candlesticks_empty_tickers(async_client: AsyncClient) -> None:
    """Empty tickers string returns empty outcomes list."""
    mock = _mock_client()
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get(
            "/api/market/event/EV-1/candlesticks",
            params={"tickers": "", "start_ts": 0, "end_ts": 1},
        )
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    data = response.json()
    assert data["status"] == "success"
    assert data["outcomes"] == []


@pytest.mark.asyncio
async def test_event_candlesticks_partial_failure(async_client: AsyncClient) -> None:
    """If one ticker's candles fail, successful tickers still return data."""
    mock = _mock_client()
    call_count = 0

    async def _side_effect(**kwargs: object) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _SAMPLE_CANDLES
        raise httpx.RequestError("timeout")

    mock.get_candlesticks = AsyncMock(side_effect=_side_effect)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get(
            "/api/market/event/EV-1/candlesticks",
            params={
                "tickers": "T1,T2",
                "start_ts": 0,
                "end_ts": 1,
            },
        )
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    data = response.json()
    assert data["status"] == "success"
    assert len(data["outcomes"]) == 2
    # One should have data, one should be empty.
    candle_counts = sorted(len(o["candlesticks"]) for o in data["outcomes"])
    assert candle_counts == [0, 2]


@pytest.mark.asyncio
async def test_event_candlesticks_series_ticker_derived(
    async_client: AsyncClient,
) -> None:
    """series_ticker is derived from event_ticker (first dash segment)."""
    mock = _mock_client()
    mock.get_candlesticks = AsyncMock(return_value={"candlesticks": []})
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get(
            "/api/market/event/KXBTC-25MAR/candlesticks",
            params={"tickers": "KXBTC-25MAR-T100", "start_ts": 0, "end_ts": 1},
        )
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    # Verify the client was called with the correct derived series_ticker.
    mock.get_candlesticks.assert_called_once()
    call_kwargs = mock.get_candlesticks.call_args
    assert call_kwargs.kwargs["series_ticker"] == "KXBTC"
