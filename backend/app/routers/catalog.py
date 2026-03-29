"""Catalog router — on-demand browsing of Kalshi series, events, and markets.

All data is fetched live from Kalshi REST endpoints on each request, with
the exception of the series list which is cached in Redis for 15 minutes
(series change rarely and the full list arrives in a single fast call).

Routes:
    GET /api/catalog/categories       — distinct categories + series count
    GET /api/catalog/series           — series list, filterable by category
    GET /api/catalog/events           — paginated events, live from Kalshi
    GET /api/catalog/events/{ticker}  — single event + nested markets
    GET /api/catalog/markets/{ticker} — single market detail

Navigation flow:
    /catalog/categories
        → /catalog/series?category=Sports
            → /catalog/events?series_ticker=KXNBA&status=open
                → /catalog/events/KXNBA-2026-03-28   (nested markets included)
                → /catalog/markets/KXNBA-2026-03-28-MIA (full detail)
"""

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.dependencies import KalshiClientDep, RedisDep
from app.routers.kalshi import (
    EventDTO,
    MarketDetailDTO,
    SeriesDTO,
    _map_market,
    _map_market_detail,
)
from app.services.catalog.series_cache import (
    get_cache_ttl,
    get_series_cached,
    invalidate_series_cache,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["catalog"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CategorySummary(BaseModel):
    name: str
    series_count: int


class CategoriesResponse(BaseModel):
    categories: list[CategorySummary]


class CatalogSeriesResponse(BaseModel):
    series: list[SeriesDTO]
    total: int
    cache_ttl_seconds: int | None = None


class CatalogEventsResponse(BaseModel):
    status: Literal["success", "upstream_failure"]
    events: list[EventDTO]
    cursor: str | None = None


class CatalogEventDetailResponse(BaseModel):
    status: Literal["success", "not_found", "upstream_failure"]
    event: EventDTO | None = None


class CatalogMarketDetailResponse(BaseModel):
    status: Literal["success", "not_found", "upstream_failure"]
    market: MarketDetailDTO | None = None


# ---------------------------------------------------------------------------
# GET /api/catalog/categories
# ---------------------------------------------------------------------------


@router.get("/catalog/categories", response_model=CategoriesResponse)
async def get_categories(
    redis: RedisDep,
    client: KalshiClientDep,
) -> CategoriesResponse:
    """Return all distinct Kalshi categories with their series count.

    Computed in-process from the cached series list — no extra Kalshi call.
    Categories are sorted alphabetically.  Use the category name as a filter
    for GET /api/catalog/series.

    Example response:
      { "categories": [
          { "name": "Crypto",    "series_count": 12 },
          { "name": "Politics",  "series_count": 47 },
          { "name": "Sports",    "series_count": 31 }
        ] }
    """
    records = await get_series_cached(redis, client)

    counts: dict[str, int] = {}
    for s in records:
        cat = s.get("category") or "Uncategorized"
        counts[cat] = counts.get(cat, 0) + 1

    categories = [
        CategorySummary(name=name, series_count=count)
        for name, count in sorted(counts.items())
    ]
    return CategoriesResponse(categories=categories)


# ---------------------------------------------------------------------------
# GET /api/catalog/series
# ---------------------------------------------------------------------------


@router.get("/catalog/series", response_model=CatalogSeriesResponse)
async def get_series(
    redis: RedisDep,
    client: KalshiClientDep,
    category: str | None = Query(
        default=None,
        description="Filter by category (case-insensitive). E.g. 'Sports', 'Crypto'.",
    ),
    sort_by: Literal["ticker", "title", "category", "frequency", "volume"] = Query(
        default="title",
        description="Field to sort by.",
    ),
    sort_order: Literal["asc", "desc"] = Query(
        default="asc",
        description="Sort direction.",
    ),
    include_volume: bool = Query(
        default=False,
        description="Enrich each series with its total traded volume. Result is cached in Redis "
                    "(2-min TTL) so sort changes after initial load are instant.",
    ),
) -> CatalogSeriesResponse:
    """Return the series list from cache, optionally filtered by category.

    The full series list is cached in Redis for 15 minutes.  Filtering and
    sorting happen in-process on the cached data — no Kalshi call on cache hit.

    Pass include_volume=true to get volume data. This is fetched from the
    documented bulk GET /series endpoint and cached in Redis, so category loads
    remain a single upstream request instead of N per-series requests.
    """
    records = await get_series_cached(redis, client, include_volume=include_volume)

    # Filter in-process (category is case-insensitive)
    if category is not None:
        cat_lower = category.lower()
        records = [r for r in records if (r.get("category") or "").lower() == cat_lower]

    # Sort in-process — volume_fp is present when include_volume=True
    reverse = sort_order == "desc"
    if sort_by == "volume":
        none_sentinel: float = float("-inf") if reverse else float("inf")
        records = sorted(
            records,
            key=lambda r: float(r["volume_fp"]) if r.get("volume_fp") is not None else none_sentinel,
            reverse=reverse,
        )
    else:
        records = sorted(records, key=lambda r: (r.get(sort_by) or "").lower(), reverse=reverse)

    series = [
        SeriesDTO(
            ticker=s["ticker"],
            title=s.get("title"),
            category=s.get("category"),
            tags=s.get("tags") or [],
            frequency=s.get("frequency"),
            volume=float(s["volume_fp"]) if s.get("volume_fp") is not None else None,
        )
        for s in records
    ]

    cache_ttl = await get_cache_ttl(redis, include_volume=include_volume)

    return CatalogSeriesResponse(
        series=series,
        total=len(series),
        cache_ttl_seconds=cache_ttl,
    )


# ---------------------------------------------------------------------------
# GET /api/catalog/events
# ---------------------------------------------------------------------------


@router.get("/catalog/events", response_model=CatalogEventsResponse)
async def get_events(
    client: KalshiClientDep,
    response: Response,
    series_ticker: str | None = Query(
        default=None,
        description="Filter by series ticker.",
    ),
    status: str | None = Query(
        default=None,
        description="Filter by event status: unopened | open | closed | settled.",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=200,
        description="Number of results per page (max 200).",
    ),
    cursor: str | None = Query(
        default=None,
        description="Pagination cursor from previous response.",
    ),
) -> CatalogEventsResponse:
    """Return a paginated list of Kalshi events, fetched live.

    Markets are NOT included in list results — use GET /api/catalog/events/{ticker}
    to retrieve a single event with its full market list.

    Typical navigation:
      1. GET /api/catalog/series?category=Sports             → pick a series_ticker
      2. GET /api/catalog/events?series_ticker=KXNBA&status=open  → pick an event
      3. GET /api/catalog/events/KXNBA-...                   → see all markets
    """
    try:
        raw = await client.get_events(
            series_ticker=series_ticker,
            status=status,
            limit=limit,
            cursor=cursor,
            with_nested_markets=False,
        )
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        logger.warning("Kalshi /events HTTP %d: %s", code, exc.request.url)
        response.status_code = 502
        return CatalogEventsResponse(
            status="upstream_failure",
            events=[],
            cursor=None,
        )
    except httpx.RequestError as exc:
        logger.warning("Kalshi /events network error: %s", exc)
        response.status_code = 502
        return CatalogEventsResponse(
            status="upstream_failure",
            events=[],
            cursor=None,
        )

    raw_events: list[dict] = raw.get("events") or []
    events = [
        EventDTO(
            event_ticker=e["event_ticker"],
            series_ticker=e.get("series_ticker"),
            title=e.get("title"),
            sub_title=e.get("sub_title"),
            category=e.get("category"),
            mutually_exclusive=e.get("mutually_exclusive"),
            markets=[],  # not requested for list view
        )
        for e in raw_events
    ]
    return CatalogEventsResponse(
        status="success",
        events=events,
        cursor=raw.get("cursor") or None,
    )


# ---------------------------------------------------------------------------
# GET /api/catalog/events/{ticker}
# ---------------------------------------------------------------------------


@router.get("/catalog/events/{ticker}", response_model=CatalogEventDetailResponse)
async def get_event_detail(
    ticker: str,
    client: KalshiClientDep,
    response: Response,
) -> CatalogEventDetailResponse:
    """Return a single Kalshi event with its full nested markets list.

    Use this to populate a market selection pane after the user picks an event
    from the events list.  All markets for the event are included inline.

    Returns 404 when the event does not exist on Kalshi.
    Returns 502 on upstream errors.
    """
    try:
        raw = await client.get_event(ticker, with_nested_markets=True)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 404:
            response.status_code = 404
            return CatalogEventDetailResponse(status="not_found", event=None)
        logger.warning("Kalshi /events/%s HTTP %d", ticker, code)
        response.status_code = 502
        return CatalogEventDetailResponse(status="upstream_failure", event=None)
    except httpx.RequestError as exc:
        logger.warning("Kalshi /events/%s network error: %s", ticker, exc)
        response.status_code = 502
        return CatalogEventDetailResponse(status="upstream_failure", event=None)

    raw_event: dict = raw.get("event") or {}
    event = EventDTO(
        event_ticker=raw_event["event_ticker"],
        series_ticker=raw_event.get("series_ticker"),
        title=raw_event.get("title"),
        sub_title=raw_event.get("sub_title"),
        category=raw_event.get("category"),
        mutually_exclusive=raw_event.get("mutually_exclusive"),
        markets=[_map_market(m) for m in (raw_event.get("markets") or [])],
    )
    return CatalogEventDetailResponse(status="success", event=event)


# ---------------------------------------------------------------------------
# GET /api/catalog/markets/{ticker}
# ---------------------------------------------------------------------------


@router.get("/catalog/markets/{ticker}", response_model=CatalogMarketDetailResponse)
async def get_market_detail(
    ticker: str,
    client: KalshiClientDep,
    response: Response,
) -> CatalogMarketDetailResponse:
    """Return full detail for a single Kalshi market.

    Includes price movement fields, strike definition, and settlement rules
    on top of the standard market browse fields.  Use this to populate an
    order entry panel or market inspection pane.

    Returns 404 when the market does not exist on Kalshi.
    Returns 502 on upstream errors.
    """
    try:
        raw = await client.get_market(ticker)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 404:
            response.status_code = 404
            return CatalogMarketDetailResponse(status="not_found", market=None)
        logger.warning("Kalshi /markets/%s HTTP %d", ticker, code)
        response.status_code = 502
        return CatalogMarketDetailResponse(status="upstream_failure", market=None)
    except httpx.RequestError as exc:
        logger.warning("Kalshi /markets/%s network error: %s", ticker, exc)
        response.status_code = 502
        return CatalogMarketDetailResponse(status="upstream_failure", market=None)

    raw_market: dict = raw.get("market") or {}
    market = _map_market_detail(raw_market)
    return CatalogMarketDetailResponse(status="success", market=market)
