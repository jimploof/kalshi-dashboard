"""Tests for app/services/db/series_repo.py.

Uses AsyncMock for the asyncpg pool — no real database connection required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.db.series_repo import get_series, upsert_series


def _make_pool(fetch_return=None, execute_return=None):
    """Build a minimal asyncpg.Pool mock with an acquire() context manager."""
    conn = AsyncMock()
    conn.executemany = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=fetch_return or [])

    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


# ---------------------------------------------------------------------------
# upsert_series
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_series_calls_executemany() -> None:
    pool, conn = _make_pool()
    records = [
        {"ticker": "KXBTCD", "title": "Bitcoin Daily", "category": "Crypto", "tags": ["bitcoin"], "frequency": "daily"},
        {"ticker": "KXETH", "title": "Ethereum", "category": "Crypto", "tags": [], "frequency": "daily"},
    ]
    result = await upsert_series(pool, records)

    conn.executemany.assert_called_once()
    assert result == 2


@pytest.mark.asyncio
async def test_upsert_series_empty_list_is_noop() -> None:
    pool, conn = _make_pool()
    result = await upsert_series(pool, [])
    conn.executemany.assert_not_called()
    assert result == 0


@pytest.mark.asyncio
async def test_upsert_series_passes_correct_tuple_shape() -> None:
    pool, conn = _make_pool()
    records = [{"ticker": "KXBTCD", "category": "Crypto"}]
    await upsert_series(pool, records)

    _, rows = conn.executemany.call_args.args
    assert len(rows) == 1
    ticker, title, category, tags, frequency = rows[0]
    assert ticker == "KXBTCD"
    assert category == "Crypto"
    assert tags == []           # defaults to empty list when missing
    assert title is None
    assert frequency is None


# ---------------------------------------------------------------------------
# get_series
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_series_no_filter_fetches_all() -> None:
    fake_row = {"ticker": "KXBTCD", "title": "BTC", "category": "Crypto", "tags": [], "frequency": "daily", "fetched_at": None}
    pool, conn = _make_pool(fetch_return=[fake_row])

    rows = await get_series(pool)

    conn.fetch.assert_called_once()
    sql_used: str = conn.fetch.call_args.args[0]
    assert "$1" not in sql_used           # no parameter placeholder without category
    assert len(rows) == 1
    assert rows[0]["ticker"] == "KXBTCD"


@pytest.mark.asyncio
async def test_get_series_with_category_passes_param() -> None:
    pool, conn = _make_pool(fetch_return=[])
    await get_series(pool, category="Crypto")

    conn.fetch.assert_called_once()
    call_args = conn.fetch.call_args
    assert call_args.args[1] == "Crypto"  # second positional arg is the category param
