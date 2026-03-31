"""
Kalshi-connected routes.

GET /api/kalshi/health              — authenticated connectivity probe (balance endpoint)
GET /api/kalshi/markets             — public market discovery (GET /markets)
GET /api/kalshi/markets/{ticker}    — single market detail with price/volume/rules context
GET /api/kalshi/events              — event list discovery / bootstrap (GET /events)
GET /api/kalshi/events/{ticker}     — single event detail with nested markets (GET /events/{event_ticker})
GET /api/kalshi/series              — series list with category filter (GET /series)
"""

import logging
from datetime import datetime
from typing import Literal

import httpx
from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from app.dependencies import KalshiClientDep, SettingsDep

logger = logging.getLogger(__name__)
router = APIRouter(tags=["kalshi"])

_SUCCESS_MESSAGE = "Kalshi connectivity and authentication verified via balance probe."
_PROVIDER = "kalshi"
_PROBE = "get_balance"


class KalshiHealthResponse(BaseModel):
    status: Literal["success", "missing_config", "auth_failure", "upstream_failure"]
    message: str
    provider: str
    authenticated: bool
    probe: str
    base_url: str
    environment: str


@router.get("/kalshi/health", response_model=KalshiHealthResponse)
async def kalshi_health(
    client: KalshiClientDep,
    settings: SettingsDep,
    response: Response,
) -> KalshiHealthResponse:
    """Probe authenticated Kalshi REST connectivity via GET /portfolio/balance.

    Returns sanitized connectivity metadata only — no account financial data.
    """
    base_url = settings.kalshi_api_base_url
    environment = settings.kalshi_env

    if not client.is_configured():
        response.status_code = 503
        return KalshiHealthResponse(
            status="missing_config",
            message="Kalshi credentials are not configured.",
            provider=_PROVIDER,
            authenticated=False,
            probe=_PROBE,
            base_url=base_url,
            environment=environment,
        )

    try:
        await client.get_balance()
        return KalshiHealthResponse(
            status="success",
            message=_SUCCESS_MESSAGE,
            provider=_PROVIDER,
            authenticated=True,
            probe=_PROBE,
            base_url=base_url,
            environment=environment,
        )
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (401, 403):
            logger.warning("Kalshi auth failure (HTTP %s)", code)
            response.status_code = 502
            return KalshiHealthResponse(
                status="auth_failure",
                message=f"Kalshi rejected the request with HTTP {code}.",
                provider=_PROVIDER,
                authenticated=False,
                probe=_PROBE,
                base_url=base_url,
                environment=environment,
            )
        logger.warning("Kalshi upstream HTTP error %s at %s", code, exc.request.url)
        response.status_code = 502
        return KalshiHealthResponse(
            status="upstream_failure",
            message=f"Kalshi returned an unexpected HTTP {code} response.",
            provider=_PROVIDER,
            authenticated=False,
            probe=_PROBE,
            base_url=base_url,
            environment=environment,
        )
    except httpx.RequestError as exc:
        logger.warning("Kalshi request error: %s", exc)
        response.status_code = 502
        return KalshiHealthResponse(
            status="upstream_failure",
            message="Could not reach Kalshi API.",
            provider=_PROVIDER,
            authenticated=False,
            probe=_PROBE,
            base_url=base_url,
            environment=environment,
        )


# ---------------------------------------------------------------------------
# GET /api/kalshi/markets — market discovery / bootstrap
# ---------------------------------------------------------------------------

_MARKETS_SUCCESS_MESSAGE = "Kalshi markets retrieved successfully."


class MarketDTO(BaseModel):
    """Browse-focused internal market representation.

    Covers the fields most useful for evaluating a market quickly in a list,
    ladder, or related-markets panel.  Sourced from GET /markets and from
    the nested markets returned by GET /events when with_nested_markets=true.

    Fields are confirmed against docs.kalshi.com/api-reference/market/get-market.
    Fields noted as deprecated in the Kalshi docs are kept while the upstream
    API still returns them, but new display code should prefer yes_sub_title
    and no_sub_title over the deprecated title/subtitle fields.
    """

    ticker: str
    series_ticker: str | None = None       # series the market belongs to
    event_ticker: str | None = None
    market_type: str | None = None         # "binary" | "scalar"
    yes_sub_title: str | None = None       # short YES side label (non-deprecated)
    no_sub_title: str | None = None        # short NO side label (non-deprecated)
    title: str | None = None              # deprecated upstream; kept while still returned
    subtitle: str | None = None           # deprecated upstream; kept while still returned
    status: str | None = None
    result: str | None = None             # settlement result: "yes" | "no" | "void" | "" for open
    open_time: datetime | None = None
    close_time: datetime | None = None
    yes_bid_dollars: str | None = None    # best YES bid price
    yes_ask_dollars: str | None = None    # best YES ask price
    last_price_dollars: str | None = None # last traded price
    volume_fp: str | None = None          # total volume in contracts
    volume_24h_fp: str | None = None      # 24h volume in contracts
    open_interest_fp: str | None = None   # outstanding contracts


def _map_market(raw: dict) -> MarketDTO:
    """Normalise a raw upstream market object into a browse-focused MarketDTO.

    Kalshi's GET /markets/{ticker} often omits series_ticker from the response.
    When it is absent, derive it from event_ticker (the first dash-delimited
    segment), which is always present and follows the pattern SERIES-...
    """
    event_ticker: str | None = raw.get("event_ticker")
    series_ticker: str | None = (
        raw.get("series_ticker")
        or (event_ticker.split("-")[0] if event_ticker else None)
    )
    return MarketDTO(
        ticker=raw["ticker"],
        series_ticker=series_ticker,
        event_ticker=event_ticker,
        market_type=raw.get("market_type"),
        yes_sub_title=raw.get("yes_sub_title"),
        no_sub_title=raw.get("no_sub_title"),
        title=raw.get("title"),
        subtitle=raw.get("subtitle"),
        status=raw.get("status"),
        result=raw.get("result"),
        open_time=raw.get("open_time"),
        close_time=raw.get("close_time"),
        yes_bid_dollars=raw.get("yes_bid_dollars"),
        yes_ask_dollars=raw.get("yes_ask_dollars"),
        last_price_dollars=raw.get("last_price_dollars"),
        volume_fp=raw.get("volume_fp"),
        volume_24h_fp=raw.get("volume_24h_fp"),
        open_interest_fp=raw.get("open_interest_fp"),
    )


def _map_market_detail(raw: dict) -> "MarketDetailDTO":
    """Normalise a raw upstream market object into a full MarketDetailDTO.

    Extends ``_map_market`` with the extra settlement, price-movement, strike,
    and rules fields that are only present on the single-market GET response.
    Defined here (alongside ``_map_market``) so both catalog.py and the
    existing kalshi.py handler can import from a single location.

    Kalshi's GET /markets/{ticker} often omits series_ticker from the response.
    When it is absent, derive it from event_ticker (the first dash-delimited
    segment), which is always present and follows the pattern SERIES-...
    """
    event_ticker: str | None = raw.get("event_ticker")
    series_ticker: str | None = (
        raw.get("series_ticker")
        or (event_ticker.split("-")[0] if event_ticker else None)
    )
    return MarketDetailDTO(
        ticker=raw["ticker"],
        series_ticker=series_ticker,
        event_ticker=event_ticker,
        market_type=raw.get("market_type"),
        yes_sub_title=raw.get("yes_sub_title"),
        no_sub_title=raw.get("no_sub_title"),
        title=raw.get("title"),
        subtitle=raw.get("subtitle"),
        status=raw.get("status"),
        result=raw.get("result"),
        open_time=raw.get("open_time"),
        close_time=raw.get("close_time"),
        yes_bid_dollars=raw.get("yes_bid_dollars"),
        yes_ask_dollars=raw.get("yes_ask_dollars"),
        last_price_dollars=raw.get("last_price_dollars"),
        volume_fp=raw.get("volume_fp"),
        volume_24h_fp=raw.get("volume_24h_fp"),
        open_interest_fp=raw.get("open_interest_fp"),
        previous_yes_bid_dollars=raw.get("previous_yes_bid_dollars"),
        previous_yes_ask_dollars=raw.get("previous_yes_ask_dollars"),
        previous_price_dollars=raw.get("previous_price_dollars"),
        notional_value_dollars=raw.get("notional_value_dollars"),
        settlement_value_dollars=raw.get("settlement_value_dollars"),
        settlement_ts=raw.get("settlement_ts"),
        strike_type=raw.get("strike_type"),
        floor_strike=raw.get("floor_strike"),
        cap_strike=raw.get("cap_strike"),
        rules_primary=raw.get("rules_primary"),
        rules_secondary=raw.get("rules_secondary"),
        is_provisional=raw.get("is_provisional"),
        fractional_trading_enabled=raw.get("fractional_trading_enabled"),
    )


class KalshiMarketsResponse(BaseModel):
    status: Literal["success", "upstream_failure"]
    message: str
    markets: list[MarketDTO]
    cursor: str | None = None


@router.get("/kalshi/markets", response_model=KalshiMarketsResponse)
async def kalshi_get_markets(
    client: KalshiClientDep,
    response: Response,
    status: str | None = Query(default=None, description="Filter by market status: unopened, open, paused, closed, settled"),
    limit: int = Query(default=100, ge=1, le=1000, description="Number of results per page (max 1000)"),
    cursor: str | None = Query(default=None, description="Pagination cursor from previous response"),
) -> KalshiMarketsResponse:
    """Retrieve markets from Kalshi for discovery and bootstrap.

    Calls the public GET /markets Kalshi endpoint. Auth headers are sent when
    credentials are configured (avoids unauthenticated rate-limit buckets) but
    are not required — the upstream endpoint is publicly accessible.

    This is a REST discovery/bootstrap endpoint only. Live market state will
    be delivered via WebSocket in a future slice.
    """
    try:
        raw = await client.get_markets(status=status, limit=limit, cursor=cursor)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        logger.warning("Kalshi /markets HTTP error %s at %s", code, exc.request.url)
        response.status_code = 502
        return KalshiMarketsResponse(
            status="upstream_failure",
            message=f"Kalshi returned HTTP {code} for /markets.",
            markets=[],
            cursor=None,
        )
    except httpx.RequestError as exc:
        logger.warning("Kalshi /markets request error: %s", exc)
        response.status_code = 502
        return KalshiMarketsResponse(
            status="upstream_failure",
            message="Could not reach Kalshi API for /markets.",
            markets=[],
            cursor=None,
        )

    raw_markets: list[dict] = raw.get("markets") or []
    markets = [_map_market(m) for m in raw_markets]
    return KalshiMarketsResponse(
        status="success",
        message=_MARKETS_SUCCESS_MESSAGE,
        markets=markets,
        cursor=raw.get("cursor") or None,
    )


# ---------------------------------------------------------------------------
# GET /api/kalshi/events — event discovery / bootstrap
# ---------------------------------------------------------------------------

_EVENTS_SUCCESS_MESSAGE = "Kalshi events retrieved successfully."


class EventDTO(BaseModel):
    """Minimal internal event representation for discovery and bootstrap use.

    Events are the natural grouping container for related markets on Kalshi.
    A market belongs to exactly one event (via event_ticker), and all markets
    in the same event represent different outcomes of the same real-world
    occurrence.  The category field on EventDTO is the primary signal for
    domain-level navigation (crypto, politics, sports, etc.).

    When with_nested_markets=True is requested, the markets list is populated
    with the same MarketDTO shape used by the /kalshi/markets endpoint.
    """

    event_ticker: str
    series_ticker: str | None = None
    title: str | None = None
    sub_title: str | None = None
    category: str | None = None
    mutually_exclusive: bool | None = None
    markets: list[MarketDTO] = []


class KalshiEventsResponse(BaseModel):
    status: Literal["success", "upstream_failure"]
    message: str
    events: list[EventDTO]
    cursor: str | None = None


@router.get("/kalshi/events", response_model=KalshiEventsResponse)
async def kalshi_get_events(
    client: KalshiClientDep,
    response: Response,
    series_ticker: str | None = Query(default=None, description="Filter by series ticker"),
    status: str | None = Query(default=None, description="Filter by event status: unopened, open, closed, settled"),
    limit: int = Query(default=100, ge=1, le=200, description="Number of results per page (max 200)"),
    cursor: str | None = Query(default=None, description="Pagination cursor from previous response"),
    with_nested_markets: bool = Query(default=False, description="When true, each event includes its nested markets"),
    min_close_ts: int | None = Query(default=None, description="Return only events where at least one market closes after this Unix timestamp (seconds)"),
    min_updated_ts: int | None = Query(default=None, description="Return only events with metadata updated after this Unix timestamp (seconds). Efficient for polling."),
) -> KalshiEventsResponse:
    """Retrieve events from Kalshi for discovery and bootstrap.

    Events are the primary grouping abstraction for related markets.  Each
    event contains one or more markets representing different outcomes of the
    same real-world occurrence.  The category field enables domain-level
    navigation across crypto, politics, sports, and other Kalshi categories.

    When with_nested_markets=True, each event includes all its markets in a
    single response — this is the recommended path for powering the workstation
    "related markets" panel from a bootstrap call.

    Calls the public GET /events Kalshi endpoint. Auth headers are sent when
    credentials are configured (avoids unauthenticated rate-limit buckets).

    This is a REST discovery/bootstrap endpoint only. Live market state will
    be delivered via WebSocket in a future slice.
    """
    try:
        raw = await client.get_events(
            series_ticker=series_ticker,
            status=status,
            limit=limit,
            cursor=cursor,
            with_nested_markets=with_nested_markets,
            min_close_ts=min_close_ts,
            min_updated_ts=min_updated_ts,
        )
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        logger.warning("Kalshi /events HTTP error %s at %s", code, exc.request.url)
        response.status_code = 502
        return KalshiEventsResponse(
            status="upstream_failure",
            message=f"Kalshi returned HTTP {code} for /events.",
            events=[],
            cursor=None,
        )
    except httpx.RequestError as exc:
        logger.warning("Kalshi /events request error: %s", exc)
        response.status_code = 502
        return KalshiEventsResponse(
            status="upstream_failure",
            message="Could not reach Kalshi API for /events.",
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
            markets=[_map_market(m) for m in (e.get("markets") or [])],
        )
        for e in raw_events
    ]
    return KalshiEventsResponse(
        status="success",
        message=_EVENTS_SUCCESS_MESSAGE,
        events=events,
        cursor=raw.get("cursor") or None,
    )


# ---------------------------------------------------------------------------
# GET /api/kalshi/events/{ticker} — single event detail
# ---------------------------------------------------------------------------

_EVENT_DETAIL_SUCCESS_MESSAGE = "Kalshi event retrieved successfully."
_EVENT_DETAIL_NOT_FOUND_MESSAGE = "Kalshi event not found."


class KalshiEventDetailResponse(BaseModel):
    status: Literal["success", "not_found", "upstream_failure"]
    message: str
    event: EventDTO | None = None


@router.get("/kalshi/events/{ticker}", response_model=KalshiEventDetailResponse)
async def kalshi_get_event(
    ticker: str,
    client: KalshiClientDep,
    response: Response,
) -> KalshiEventDetailResponse:
    """Retrieve a single Kalshi event by ticker, including all nested markets.

    Always requests with_nested_markets=true so that the event object contains
    its full market list in a single round-trip.  This is the direct lookup
    path for powering the workstation "related markets" panel when a user
    opens a specific market — identify the event_ticker from the market, then
    call this endpoint to get all sibling markets.

    Returns 404 (not_found) when Kalshi responds with HTTP 404.
    Returns 502 (upstream_failure) for other upstream errors.
    """
    try:
        raw = await client.get_event(ticker, with_nested_markets=True)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 404:
            response.status_code = 404
            return KalshiEventDetailResponse(
                status="not_found",
                message=_EVENT_DETAIL_NOT_FOUND_MESSAGE,
                event=None,
            )
        logger.warning("Kalshi /events/%s HTTP error %s", ticker, code)
        response.status_code = 502
        return KalshiEventDetailResponse(
            status="upstream_failure",
            message=f"Kalshi returned HTTP {code} for /events/{ticker}.",
            event=None,
        )
    except httpx.RequestError as exc:
        logger.warning("Kalshi /events/%s request error: %s", ticker, exc)
        response.status_code = 502
        return KalshiEventDetailResponse(
            status="upstream_failure",
            message=f"Could not reach Kalshi API for /events/{ticker}.",
            event=None,
        )

    # Normalise: prefer event.markets (populated when with_nested_markets=true)
    # and ignore the deprecated top-level ``markets`` field.
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
    return KalshiEventDetailResponse(
        status="success",
        message=_EVENT_DETAIL_SUCCESS_MESSAGE,
        event=event,
    )


# ---------------------------------------------------------------------------
# GET /api/kalshi/series — series list / category navigation
# ---------------------------------------------------------------------------

_SERIES_SUCCESS_MESSAGE = "Kalshi series retrieved successfully."


class SeriesDTO(BaseModel):
    """Minimal internal series representation for category navigation.

    A series is a template for recurring events (e.g. "Monthly Jobs Report",
    "Daily Bitcoin Price").  The category and tags fields are the primary
    signals for the workstation category-level navigation pane, which lets
    users browse available market groups by domain (crypto, politics, sports,
    etc.).
    """

    ticker: str
    title: str | None = None
    category: str | None = None
    tags: list[str] = []
    frequency: str | None = None
    volume: float | None = None


class KalshiSeriesResponse(BaseModel):
    status: Literal["success", "upstream_failure"]
    message: str
    series: list[SeriesDTO]


@router.get("/kalshi/series", response_model=KalshiSeriesResponse)
async def kalshi_get_series(
    client: KalshiClientDep,
    response: Response,
    category: str | None = Query(default=None, description="Filter by category (e.g. crypto, politics, sports)"),
    tags: str | None = Query(default=None, description="Filter by tags (comma-separated)"),
    include_volume: bool = Query(default=False, description="When true, request documented series volume_fp data from Kalshi"),
) -> KalshiSeriesResponse:
    """Retrieve series from Kalshi for category-level navigation.

    Series are templates for recurring events and carry the category and tags
    that power the workstation domain navigation pane.  Use the category param
    to narrow to a specific domain; leave it empty to get all series.

    Note: the Kalshi GET /series endpoint has no pagination cursor — all
    matching series are returned in a single response per the documented API.

    Calls the public GET /series Kalshi endpoint.  Auth headers are sent when
    credentials are configured (avoids unauthenticated rate-limit buckets).
    """
    try:
        raw = await client.get_series(category=category, tags=tags, include_volume=include_volume)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        logger.warning("Kalshi /series HTTP error %s at %s", code, exc.request.url)
        response.status_code = 502
        return KalshiSeriesResponse(
            status="upstream_failure",
            message=f"Kalshi returned HTTP {code} for /series.",
            series=[],
        )
    except httpx.RequestError as exc:
        logger.warning("Kalshi /series request error: %s", exc)
        response.status_code = 502
        return KalshiSeriesResponse(
            status="upstream_failure",
            message="Could not reach Kalshi API for /series.",
            series=[],
        )

    raw_series: list[dict] = raw.get("series") or []
    series = [
        SeriesDTO(
            ticker=s["ticker"],
            title=s.get("title"),
            category=s.get("category"),
            tags=s.get("tags") or [],
            frequency=s.get("frequency"),
            volume=float(s["volume_fp"]) if s.get("volume_fp") is not None else None,
        )
        for s in raw_series
    ]
    return KalshiSeriesResponse(
        status="success",
        message=_SERIES_SUCCESS_MESSAGE,
        series=series,
    )


# ---------------------------------------------------------------------------
# GET /api/kalshi/markets/{ticker} — single market detail
# ---------------------------------------------------------------------------

_MARKET_DETAIL_SUCCESS_MESSAGE = "Kalshi market retrieved successfully."
_MARKET_DETAIL_NOT_FOUND_MESSAGE = "Kalshi market not found."


class MarketDetailDTO(MarketDTO):
    """Extended single-market detail DTO for GET /markets/{ticker}.

    Inherits all browse fields from MarketDTO and adds settlement state,
    price-movement context, strike definition, and market rules — the fields
    needed to render a full market inspection pane or inform order entry.

    Fields confirmed from docs.kalshi.com/api-reference/market/get-market.
    Some documented upstream fields are intentionally omitted from this
    normalized DTO when they are not currently needed by the product surface.
    """

    previous_yes_bid_dollars: str | None = None   # best YES bid price 24h ago
    previous_yes_ask_dollars: str | None = None   # best YES ask price 24h ago
    previous_price_dollars: str | None = None     # last traded price 24h ago
    notional_value_dollars: str | None = None     # total value of one contract at settlement
    settlement_value_dollars: str | None = None   # YES/LONG settlement value; only after determination
    settlement_ts: datetime | None = None          # settlement timestamp; only for settled markets
    strike_type: str | None = None                 # greater | less | between | functional | custom | ...
    floor_strike: float | None = None              # minimum expiration value for YES settlement
    cap_strike: float | None = None                # maximum expiration value for YES settlement
    rules_primary: str | None = None               # plain-language primary settlement rules
    rules_secondary: str | None = None             # plain-language secondary market terms
    is_provisional: bool | None = None             # may be removed post-determination if no activity
    fractional_trading_enabled: bool | None = None


class KalshiMarketDetailResponse(BaseModel):
    status: Literal["success", "not_found", "upstream_failure"]
    message: str
    market: MarketDetailDTO | None = None


@router.get("/kalshi/markets/{ticker}", response_model=KalshiMarketDetailResponse)
async def kalshi_get_market(
    ticker: str,
    client: KalshiClientDep,
    response: Response,
) -> KalshiMarketDetailResponse:
    """Retrieve a single Kalshi market by ticker with full price and rules context.

    Returns the enriched MarketDetailDTO, which adds settlement state, price
    movement, strike definition, and rules fields on top of the browse-level
    MarketDTO fields.  This is the lookup path for populating a market
    inspection pane or providing order entry context.

    Returns 404 (not_found) when Kalshi responds HTTP 404.
    Returns 502 (upstream_failure) for other upstream errors.
    """
    try:
        raw = await client.get_market(ticker)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 404:
            response.status_code = 404
            return KalshiMarketDetailResponse(
                status="not_found",
                message=_MARKET_DETAIL_NOT_FOUND_MESSAGE,
                market=None,
            )
        logger.warning("Kalshi /markets/%s HTTP error %s", ticker, code)
        response.status_code = 502
        return KalshiMarketDetailResponse(
            status="upstream_failure",
            message=f"Kalshi returned HTTP {code} for /markets/{ticker}.",
            market=None,
        )
    except httpx.RequestError as exc:
        logger.warning("Kalshi /markets/%s request error: %s", ticker, exc)
        response.status_code = 502
        return KalshiMarketDetailResponse(
            status="upstream_failure",
            message=f"Could not reach Kalshi API for /markets/{ticker}.",
            market=None,
        )

    raw_market: dict = raw.get("market") or {}
    market = _map_market_detail(raw_market)
    return KalshiMarketDetailResponse(
        status="success",
        message=_MARKET_DETAIL_SUCCESS_MESSAGE,
        market=market,
    )

