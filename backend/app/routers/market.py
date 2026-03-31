"""
Market detail and live-data router.

REST endpoints (mounted at /api):
  GET /api/market/{ticker}                  — full market detail (REST snapshot)
  GET /api/market/{ticker}/candlesticks     — OHLCV candlestick history for charting
  GET /api/market/{ticker}/orderbook        — current order book depth
  GET /api/market/event/{event_ticker}/outcomes       — sibling markets for an event
  GET /api/market/event/{event_ticker}/candlesticks   — batch candlestick fetch for event outcomes

WebSocket endpoint (mounted at /ws):
  WS  /ws/market/{ticker}                   — live ticker + orderbook stream

WebSocket lifecycle
-------------------
The browser connects to /ws/market/{ticker} through the Angular dev proxy.
This handler accepts the connection, registers it with the KalshiWsManager,
and blocks until the client disconnects.  The manager fans out Kalshi WS
messages (orderbook_snapshot, orderbook_delta, ticker updates) to all
registered frontend connections for that market.
"""

import asyncio
import logging
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.dependencies import KalshiClientDep
from app.routers.kalshi import MarketDetailDTO, _map_market_detail

logger = logging.getLogger(__name__)

# REST routes are included at prefix "/api"
router_rest = APIRouter(tags=["market"])

# WS routes are included at prefix "/ws"
router_ws = APIRouter(tags=["market"])


# ---------------------------------------------------------------------------
# REST response models
# ---------------------------------------------------------------------------


class MarketViewResponse(BaseModel):
    """Response for GET /api/market/{ticker}."""

    status: Literal["success", "not_found", "upstream_failure"]
    market: MarketDetailDTO | None = None


class CandlestickDTO(BaseModel):
    """Single OHLCV candlestick bar.

    Prices are raw cent values (0–100 integer range) matching the Kalshi API.
    ``ts`` is the ``end_period_ts`` field from the Kalshi response (Unix seconds).
    """

    ts: int      # end_period_ts (Unix seconds)
    open: int    # cents 0–100
    high: int
    low: int
    close: int
    volume: int  # contracts traded in this period


class CandlesticksResponse(BaseModel):
    """Response for GET /api/market/{ticker}/candlesticks."""

    status: Literal["success", "not_found", "upstream_failure"]
    ticker: str
    series_ticker: str
    period_interval: int
    candlesticks: list[CandlestickDTO]


class OrderbookLevelDTO(BaseModel):
    """Single price level in the order book.

    ``price`` is in cents (0–100).
    """

    price: int
    quantity: int


class OrderbookResponse(BaseModel):
    """Response for GET /api/market/{ticker}/orderbook.

    ``yes`` levels are sorted descending (best YES bid first).
    ``no`` levels are sorted descending (best NO bid first).
    """

    status: Literal["success", "not_found", "upstream_failure"]
    ticker: str
    yes: list[OrderbookLevelDTO]
    no: list[OrderbookLevelDTO]


# ---------------------------------------------------------------------------
# REST: GET /api/market/{ticker}
# ---------------------------------------------------------------------------


@router_rest.get("/market/{ticker}", response_model=MarketViewResponse)
async def get_market_view(
    ticker: str,
    client: KalshiClientDep,
) -> MarketViewResponse:
    """Return full market detail for the trading view panel.

    Fetches the single-market endpoint from Kalshi and normalises the response
    into a ``MarketDetailDTO``.  This is the REST bootstrap call for the
    trading view — live updates arrive over the WS endpoint.
    """
    try:
        raw = await client.get_market(ticker)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return MarketViewResponse(status="not_found")
        logger.error("Kalshi upstream error for market %s: %s", ticker, exc)
        return MarketViewResponse(status="upstream_failure")
    except httpx.RequestError as exc:
        logger.error("Kalshi request error for market %s: %s", ticker, exc)
        return MarketViewResponse(status="upstream_failure")

    market_raw = raw.get("market") or {}
    return MarketViewResponse(
        status="success",
        market=_map_market_detail(market_raw),
    )


# ---------------------------------------------------------------------------
# REST: GET /api/market/{ticker}/candlesticks
# ---------------------------------------------------------------------------


@router_rest.get("/market/{ticker}/candlesticks", response_model=CandlesticksResponse)
async def get_market_candlesticks(
    ticker: str,
    client: KalshiClientDep,
    series_ticker: str = Query(..., description="Series ticker for this market (e.g. KXBTC)"),
    start_ts: int = Query(..., description="Range start (Unix seconds)"),
    end_ts: int = Query(..., description="Range end (Unix seconds)"),
    period_interval: int = Query(1, ge=1, le=1440, description="Candle width in minutes"),
) -> CandlesticksResponse:
    """Return OHLCV candlestick history for charting.

    Proxies the Kalshi
    ``GET /series/{series_ticker}/markets/{ticker}/candlesticks`` endpoint and
    normalises the response.  The ``series_ticker`` query parameter is required
    because Kalshi routes the candlestick call through the series hierarchy.

    Prices in the response are raw cent integers (0–100).
    """
    try:
        raw = await client.get_candlesticks(
            series_ticker=series_ticker,
            market_ticker=ticker,
            start_ts=start_ts,
            end_ts=end_ts,
            period_interval=period_interval,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return CandlesticksResponse(
                status="not_found",
                ticker=ticker,
                series_ticker=series_ticker,
                period_interval=period_interval,
                candlesticks=[],
            )
        logger.error("Kalshi candlestick error for %s: %s", ticker, exc)
        return CandlesticksResponse(
            status="upstream_failure",
            ticker=ticker,
            series_ticker=series_ticker,
            period_interval=period_interval,
            candlesticks=[],
        )
    except httpx.RequestError as exc:
        logger.error("Kalshi candlestick request error for %s: %s", ticker, exc)
        return CandlesticksResponse(
            status="upstream_failure",
            ticker=ticker,
            series_ticker=series_ticker,
            period_interval=period_interval,
            candlesticks=[],
        )

    raw_candles: list[dict] = raw.get("candlesticks") or []
    candles: list[CandlestickDTO] = []
    for c in raw_candles:
        # Kalshi candlestick API returns prices as dollar strings under
        # price.{open,high,low,close}_dollars (confirmed from live response).
        # Convert to integer cents (×100) to match our internal contract.
        # Volume is returned as volume_fp (fixed-point string), not "volume".
        price = c.get("price") or {}

        def _dollars_to_cents(val: object) -> int:
            """Coerce a dollar string/float to integer cents."""
            try:
                return round(float(val) * 100)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 0

        candles.append(
            CandlestickDTO(
                ts=c.get("end_period_ts", 0),
                open=_dollars_to_cents(price.get("open_dollars")),
                high=_dollars_to_cents(price.get("high_dollars")),
                low=_dollars_to_cents(price.get("low_dollars")),
                close=_dollars_to_cents(price.get("close_dollars")),
                volume=round(float(c.get("volume_fp") or 0)),
            )
        )

    return CandlesticksResponse(
        status="success",
        ticker=ticker,
        series_ticker=series_ticker,
        period_interval=period_interval,
        candlesticks=candles,
    )


# ---------------------------------------------------------------------------
# REST: GET /api/market/{ticker}/orderbook
# ---------------------------------------------------------------------------


@router_rest.get("/market/{ticker}/orderbook", response_model=OrderbookResponse)
async def get_market_orderbook(
    ticker: str,
    client: KalshiClientDep,
    depth: int = Query(10, ge=1, le=50, description="Price levels per side"),
) -> OrderbookResponse:
    """Return current order book depth for a market.

    Prices are integers in cents (0–100).  ``yes`` levels are sorted descending
    (best YES bid at index 0).  ``no`` levels are sorted descending (best NO
    bid at index 0, equivalent to the lowest YES ask).
    """
    try:
        raw = await client.get_market_orderbook(ticker, depth=depth)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return OrderbookResponse(status="not_found", ticker=ticker, yes=[], no=[])
        logger.error("Kalshi orderbook error for %s: %s", ticker, exc)
        return OrderbookResponse(status="upstream_failure", ticker=ticker, yes=[], no=[])
    except httpx.RequestError as exc:
        logger.error("Kalshi orderbook request error for %s: %s", ticker, exc)
        return OrderbookResponse(status="upstream_failure", ticker=ticker, yes=[], no=[])

    # Kalshi returns "orderbook_fp" (not "orderbook"), with price arrays under
    # "yes_dollars" and "no_dollars" where prices are dollar strings.
    # Convert each price to integer cents for consistency with WS messages.
    orderbook = (raw.get("orderbook_fp") or {})

    def _ob_cents(val: object) -> int:
        try:
            return round(float(val) * 100)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    yes_levels = [
        OrderbookLevelDTO(price=_ob_cents(p), quantity=round(float(q)))
        for p, q in (orderbook.get("yes_dollars") or [])
    ]
    no_levels = [
        OrderbookLevelDTO(price=_ob_cents(p), quantity=round(float(q)))
        for p, q in (orderbook.get("no_dollars") or [])
    ]

    return OrderbookResponse(
        status="success",
        ticker=ticker,
        yes=yes_levels,
        no=no_levels,
    )


# ---------------------------------------------------------------------------
# REST: GET /api/market/event/{event_ticker}/outcomes
# ---------------------------------------------------------------------------


class EventOutcomeDTO(BaseModel):
    """Summary of a single market/outcome within an event."""

    ticker: str
    yes_sub_title: str | None = None
    last_price_dollars: str | None = None
    status: str | None = None


class EventOutcomesResponse(BaseModel):
    """Response for GET /api/market/event/{event_ticker}/outcomes."""

    status: Literal["success", "not_found", "upstream_failure"]
    event_ticker: str
    title: str | None = None
    mutually_exclusive: bool | None = None
    outcomes: list[EventOutcomeDTO]


@router_rest.get(
    "/market/event/{event_ticker}/outcomes",
    response_model=EventOutcomesResponse,
)
async def get_event_outcomes(
    event_ticker: str,
    client: KalshiClientDep,
) -> EventOutcomesResponse:
    """Return sibling markets for an event, sorted by current price descending.

    Used by the multi-outcome event chart to determine which outcome lines to
    display.  Fetches the event with nested markets from Kalshi and returns a
    slim projection sorted by ``last_price_dollars`` descending.
    """
    try:
        raw = await client.get_event(event_ticker, with_nested_markets=True)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return EventOutcomesResponse(
                status="not_found", event_ticker=event_ticker, outcomes=[],
            )
        logger.error("Kalshi event error for %s: %s", event_ticker, exc)
        return EventOutcomesResponse(
            status="upstream_failure", event_ticker=event_ticker, outcomes=[],
        )
    except httpx.RequestError as exc:
        logger.error("Kalshi event request error for %s: %s", event_ticker, exc)
        return EventOutcomesResponse(
            status="upstream_failure", event_ticker=event_ticker, outcomes=[],
        )

    event_data = raw.get("event") or {}
    raw_markets: list[dict] = event_data.get("markets") or []

    outcomes = [
        EventOutcomeDTO(
            ticker=m.get("ticker", ""),
            yes_sub_title=m.get("yes_sub_title"),
            last_price_dollars=m.get("last_price_dollars"),
            status=m.get("status"),
        )
        for m in raw_markets
    ]

    # Sort by current price descending (highest probability first).
    def _price_sort_key(o: EventOutcomeDTO) -> float:
        try:
            return float(o.last_price_dollars or "0")
        except (TypeError, ValueError):
            return 0.0

    outcomes.sort(key=_price_sort_key, reverse=True)

    return EventOutcomesResponse(
        status="success",
        event_ticker=event_ticker,
        title=event_data.get("title"),
        mutually_exclusive=event_data.get("mutually_exclusive"),
        outcomes=outcomes,
    )


# ---------------------------------------------------------------------------
# REST: GET /api/market/event/{event_ticker}/candlesticks
# ---------------------------------------------------------------------------


class OutcomeCandlesticks(BaseModel):
    """Candlestick data for a single outcome within a batch response."""

    ticker: str
    candlesticks: list[CandlestickDTO]


class EventCandlesticksResponse(BaseModel):
    """Response for GET /api/market/event/{event_ticker}/candlesticks."""

    status: Literal["success", "upstream_failure"]
    event_ticker: str
    period_interval: int
    outcomes: list[OutcomeCandlesticks]


@router_rest.get(
    "/market/event/{event_ticker}/candlesticks",
    response_model=EventCandlesticksResponse,
)
async def get_event_candlesticks(
    event_ticker: str,
    client: KalshiClientDep,
    tickers: str = Query(
        ...,
        description="Comma-separated market tickers to fetch candlesticks for",
    ),
    start_ts: int = Query(..., description="Range start (Unix seconds)"),
    end_ts: int = Query(..., description="Range end (Unix seconds)"),
    period_interval: int = Query(
        1, ge=1, le=1440, description="Candle width in minutes",
    ),
) -> EventCandlesticksResponse:
    """Batch-fetch candlestick history for multiple outcomes in an event.

    Fetches candlesticks for each requested ticker in parallel using the
    existing per-market candlestick endpoint on Kalshi.  The ``series_ticker``
    is derived from the ``event_ticker`` (first dash segment).
    """
    series_ticker = event_ticker.split("-")[0] if "-" in event_ticker else event_ticker
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]

    if not ticker_list:
        return EventCandlesticksResponse(
            status="success",
            event_ticker=event_ticker,
            period_interval=period_interval,
            outcomes=[],
        )

    async def _fetch_one(market_ticker: str) -> OutcomeCandlesticks:
        try:
            raw = await client.get_candlesticks(
                series_ticker=series_ticker,
                market_ticker=market_ticker,
                start_ts=start_ts,
                end_ts=end_ts,
                period_interval=period_interval,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning(
                "Candlestick fetch failed for %s: %s", market_ticker, exc,
            )
            return OutcomeCandlesticks(ticker=market_ticker, candlesticks=[])

        raw_candles: list[dict] = raw.get("candlesticks") or []
        candles: list[CandlestickDTO] = []
        for c in raw_candles:
            price = c.get("price") or {}

            def _dollars_to_cents(val: object) -> int:
                try:
                    return round(float(val) * 100)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    return 0

            candles.append(
                CandlestickDTO(
                    ts=c.get("end_period_ts", 0),
                    open=_dollars_to_cents(price.get("open_dollars")),
                    high=_dollars_to_cents(price.get("high_dollars")),
                    low=_dollars_to_cents(price.get("low_dollars")),
                    close=_dollars_to_cents(price.get("close_dollars")),
                    volume=round(float(c.get("volume_fp") or 0)),
                )
            )

        return OutcomeCandlesticks(ticker=market_ticker, candlesticks=candles)

    results = await asyncio.gather(*[_fetch_one(t) for t in ticker_list])

    return EventCandlesticksResponse(
        status="success",
        event_ticker=event_ticker,
        period_interval=period_interval,
        outcomes=list(results),
    )


# ---------------------------------------------------------------------------
# WebSocket: /ws/market/{ticker}
# ---------------------------------------------------------------------------


@router_ws.websocket("/market/{ticker}")
async def market_ws_endpoint(
    ticker: str,
    websocket: WebSocket,
    request: Request,
) -> None:
    """Live market data WebSocket proxy.

    The frontend connects here; the backend subscribes to the Kalshi WS
    channels ``orderbook_delta`` and ``ticker`` for this market and relays
    all channel messages to this client.

    Automatic lifecycle:
    - On connect   → subscribe_client(ticker, ws)
    - While alive  → relay Kalshi messages (fan-out handled by KalshiWsManager)
    - On disconnect → unsubscribe_client(ticker, ws)

    Message format relayed to the frontend mirrors the Kalshi WS v2 schema:
      {"type": "ticker"|"orderbook_snapshot"|"orderbook_delta",
       "sid": int, "seq": int, "msg": {..., "market_ticker": "..."}}
    """
    await websocket.accept()

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager is None:
        await websocket.send_json({"type": "error", "msg": "WS manager not initialised"})
        await websocket.close(code=1011)
        return

    await ws_manager.subscribe_client(ticker, websocket)
    logger.info("Frontend WS client subscribed to market %s", ticker)

    try:
        # Keep the WebSocket alive until the client disconnects.
        # The KalshiWsManager writes inbound Kalshi messages to this socket;
        # we only need to handle explicit client messages or disconnection here.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("Market WS handler exception for %s: %s", ticker, exc)
    finally:
        await ws_manager.unsubscribe_client(ticker, websocket)
        logger.info("Frontend WS client unsubscribed from market %s", ticker)
