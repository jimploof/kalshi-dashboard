"""DB-backed browse routes — serve series, events, and markets from local PostgreSQL.

These routes read from the locally hydrated database tables populated by
HydrationService.  They are the primary consumer-facing browse API for the
workstation.  The existing /api/kalshi/* routes remain unchanged as live
Kalshi proxies (useful for debugging and one-off lookups).

Routes:
    GET /api/browse/series              — series list, optional category filter
    GET /api/browse/events              — event list with filters + pagination
    GET /api/browse/markets             — market list with filters + pagination
    GET /api/browse/markets/{ticker}    — single market detail
"""

import logging
from datetime import datetime
from typing import Literal

import redis.asyncio as aioredis
from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from app.dependencies import DbDep, RedisDep
from app.services.db import events_repo, series_repo

logger = logging.getLogger(__name__)
router = APIRouter(tags=["browse"])

_REDIS_EVENTS_LAST_RUN_KEY = "hydration:events:last_run"
_REDIS_SERIES_LAST_RUN_KEY = "hydration:series:last_run"


# ---------------------------------------------------------------------------
# Shared response components
# ---------------------------------------------------------------------------

async def _get_hydration_last_run(redis: aioredis.Redis, key: str) -> str | None:
    try:
        return await redis.get(key)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Series browse DTO — matches SeriesDTO shape from kalshi.py
# ---------------------------------------------------------------------------

class BrowseSeriesItem(BaseModel):
    ticker: str
    title: str | None = None
    category: str | None = None
    tags: list[str] = []
    frequency: str | None = None


class BrowseSeriesResponse(BaseModel):
    status: Literal["success"]
    series: list[BrowseSeriesItem]
    hydration_last_run: str | None = None


@router.get("/browse/series", response_model=BrowseSeriesResponse)
async def browse_series(
    pool: DbDep,
    redis: RedisDep,
    category: str | None = Query(default=None, description="Filter by category (case-sensitive, e.g. 'Crypto', 'Politics')"),
) -> BrowseSeriesResponse:
    """Return series from local DB, optionally filtered by category.

    Categories are title-case strings as returned by Kalshi (e.g. 'Crypto',
    'Politics', 'Sports').  Use GET /api/kalshi/series without a category
    filter to discover all available category strings.
    """
    rows = await series_repo.get_series(pool, category=category)
    items = [
        BrowseSeriesItem(
            ticker=r["ticker"],
            title=r.get("title"),
            category=r.get("category"),
            tags=r.get("tags") or [],
            frequency=r.get("frequency"),
        )
        for r in rows
    ]
    last_run = await _get_hydration_last_run(redis, _REDIS_SERIES_LAST_RUN_KEY)
    return BrowseSeriesResponse(status="success", series=items, hydration_last_run=last_run)


# ---------------------------------------------------------------------------
# Events browse DTO — matches EventDTO shape from kalshi.py
# ---------------------------------------------------------------------------

class BrowseMarketItem(BaseModel):
    ticker: str
    event_ticker: str | None = None
    market_type: str | None = None
    yes_sub_title: str | None = None
    no_sub_title: str | None = None
    title: str | None = None
    subtitle: str | None = None
    status: str | None = None
    open_time: datetime | None = None
    close_time: datetime | None = None
    yes_bid_dollars: str | None = None
    yes_ask_dollars: str | None = None
    last_price_dollars: str | None = None
    volume_fp: str | None = None
    volume_24h_fp: str | None = None
    open_interest_fp: str | None = None


class BrowseEventItem(BaseModel):
    event_ticker: str
    series_ticker: str | None = None
    title: str | None = None
    sub_title: str | None = None
    category: str | None = None
    mutually_exclusive: bool | None = None
    status: str | None = None


class BrowseEventsResponse(BaseModel):
    status: Literal["success"]
    events: list[BrowseEventItem]
    cursor: str | None = None
    hydration_last_run: str | None = None


@router.get("/browse/events", response_model=BrowseEventsResponse)
async def browse_events(
    pool: DbDep,
    redis: RedisDep,
    series_ticker: str | None = Query(default=None),
    status: str | None = Query(default=None, description="unopened | open | closed | settled"),
    limit: int = Query(default=100, ge=1, le=200),
    cursor: str | None = Query(default=None),
    min_close_ts: int | None = Query(default=None, description="Unix timestamp (seconds) — exclude events whose markets all close before this time"),
    min_updated_ts: int | None = Query(default=None, description="Unix timestamp (seconds) — events hydrated after this time"),
) -> BrowseEventsResponse:
    """Return events from local DB with optional filters and cursor pagination."""
    rows, next_cursor = await events_repo.get_events(
        pool,
        series_ticker=series_ticker,
        status=status,
        limit=limit,
        cursor=cursor,
        min_close_ts=min_close_ts,
        min_updated_ts=min_updated_ts,
    )
    items = [
        BrowseEventItem(
            event_ticker=r["event_ticker"],
            series_ticker=r.get("series_ticker"),
            title=r.get("title"),
            sub_title=r.get("sub_title"),
            category=r.get("category"),
            mutually_exclusive=r.get("mutually_exclusive"),
            status=r.get("status"),
        )
        for r in rows
    ]
    last_run = await _get_hydration_last_run(redis, _REDIS_EVENTS_LAST_RUN_KEY)
    return BrowseEventsResponse(
        status="success",
        events=items,
        cursor=next_cursor,
        hydration_last_run=last_run,
    )


# ---------------------------------------------------------------------------
# Markets browse routes
# ---------------------------------------------------------------------------

class BrowseMarketsResponse(BaseModel):
    status: Literal["success"]
    markets: list[BrowseMarketItem]
    cursor: str | None = None
    hydration_last_run: str | None = None


class BrowseMarketDetailResponse(BaseModel):
    status: Literal["success", "not_found"]
    message: str
    market: BrowseMarketItem | None = None
    hydration_last_run: str | None = None


def _map_browse_market(r: dict) -> BrowseMarketItem:
    return BrowseMarketItem(
        ticker=r["ticker"],
        event_ticker=r.get("event_ticker"),
        market_type=r.get("market_type"),
        yes_sub_title=r.get("yes_sub_title"),
        no_sub_title=r.get("no_sub_title"),
        title=r.get("title"),
        subtitle=r.get("subtitle"),
        status=r.get("status"),
        open_time=r.get("open_time"),
        close_time=r.get("close_time"),
        yes_bid_dollars=r.get("yes_bid_dollars"),
        yes_ask_dollars=r.get("yes_ask_dollars"),
        last_price_dollars=r.get("last_price_dollars"),
        volume_fp=r.get("volume_fp"),
        volume_24h_fp=r.get("volume_24h_fp"),
        open_interest_fp=r.get("open_interest_fp"),
    )


@router.get("/browse/markets", response_model=BrowseMarketsResponse)
async def browse_markets(
    pool: DbDep,
    redis: RedisDep,
    event_ticker: str | None = Query(default=None),
    status: str | None = Query(default=None, description="unopened | open | closed | settled"),
    limit: int = Query(default=100, ge=1, le=1000),
    cursor: str | None = Query(default=None),
) -> BrowseMarketsResponse:
    """Return markets from local DB with optional filters and cursor pagination."""
    rows, next_cursor = await events_repo.get_markets(
        pool,
        event_ticker=event_ticker,
        status=status,
        limit=limit,
        cursor=cursor,
    )
    items = [_map_browse_market(r) for r in rows]
    last_run = await _get_hydration_last_run(redis, _REDIS_EVENTS_LAST_RUN_KEY)
    return BrowseMarketsResponse(
        status="success",
        markets=items,
        cursor=next_cursor,
        hydration_last_run=last_run,
    )


@router.get("/browse/markets/{ticker}", response_model=BrowseMarketDetailResponse)
async def browse_market_detail(
    ticker: str,
    pool: DbDep,
    redis: RedisDep,
    response: Response,
) -> BrowseMarketDetailResponse:
    """Return a single market by ticker from local DB."""
    row = await events_repo.get_market(pool, ticker)
    last_run = await _get_hydration_last_run(redis, _REDIS_EVENTS_LAST_RUN_KEY)
    if row is None:
        response.status_code = 404
        return BrowseMarketDetailResponse(
            status="not_found",
            message=f"Market {ticker!r} not found in local DB. It may not have been hydrated yet.",
            market=None,
            hydration_last_run=last_run,
        )
    return BrowseMarketDetailResponse(
        status="success",
        message="Market retrieved from local database.",
        market=_map_browse_market(row),
        hydration_last_run=last_run,
    )
