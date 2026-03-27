"""Tests for app/services/db/events_repo.py.

Uses AsyncMock for the asyncpg pool — no real database connection required.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.db.events_repo import (
    get_events,
    get_market,
    get_markets,
    upsert_events,
    upsert_markets,
)


def _make_pool(fetch_return=None, fetchrow_return=None):
    conn = AsyncMock()
    conn.executemany = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)

    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


_SAMPLE_EVENT = {
    "event_ticker": "KXBTCD-26MAR",
    "series_ticker": "KXBTCD",
    "title": "Bitcoin March 26",
    "sub_title": None,
    "category": "Crypto",
    "mutually_exclusive": True,
    "status": "open",
}

_SAMPLE_MARKET = {
    "ticker": "KXBTCD-26MAR-T95000",
    "event_ticker": "KXBTCD-26MAR",
    "market_type": "binary",
    "yes_sub_title": "Yes",
    "no_sub_title": "No",
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
}


# ---------------------------------------------------------------------------
# upsert_events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_events_calls_executemany() -> None:
    pool, conn = _make_pool()
    n = await upsert_events(pool, [_SAMPLE_EVENT])
    conn.executemany.assert_called_once()
    assert n == 1


@pytest.mark.asyncio
async def test_upsert_events_empty_is_noop() -> None:
    pool, conn = _make_pool()
    n = await upsert_events(pool, [])
    conn.executemany.assert_not_called()
    assert n == 0


# ---------------------------------------------------------------------------
# upsert_markets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_markets_calls_executemany() -> None:
    pool, conn = _make_pool()
    n = await upsert_markets(pool, [_SAMPLE_MARKET])
    conn.executemany.assert_called_once()
    assert n == 1


# ---------------------------------------------------------------------------
# get_events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_events_with_series_ticker_filter() -> None:
    pool, conn = _make_pool(fetch_return=[_SAMPLE_EVENT])
    rows, next_cursor = await get_events(pool, series_ticker="KXBTCD", limit=10)

    conn.fetch.assert_called_once()
    sql: str = conn.fetch.call_args.args[0]
    assert "series_ticker" in sql
    assert next_cursor is None   # only 1 row returned, limit=10 → no next page


@pytest.mark.asyncio
async def test_get_events_cursor_pagination() -> None:
    """When returned rows == limit+1, a next_cursor is produced."""
    # Return limit+1 rows to trigger cursor generation (limit=2, return 3 rows)
    rows_data = [dict(_SAMPLE_EVENT, event_ticker=f"EVT-{i}") for i in range(3)]
    pool, conn = _make_pool(fetch_return=rows_data)

    rows, next_cursor = await get_events(pool, limit=2)
    assert len(rows) == 2
    assert next_cursor is not None


# ---------------------------------------------------------------------------
# get_market
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_market_found() -> None:
    pool, conn = _make_pool(fetchrow_return=_SAMPLE_MARKET)
    result = await get_market(pool, "KXBTCD-26MAR-T95000")
    assert result is not None
    assert result["ticker"] == "KXBTCD-26MAR-T95000"


@pytest.mark.asyncio
async def test_get_market_not_found_returns_none() -> None:
    pool, conn = _make_pool(fetchrow_return=None)
    result = await get_market(pool, "DOES-NOT-EXIST")
    assert result is None
