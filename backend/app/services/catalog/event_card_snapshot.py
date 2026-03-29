from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from app.routers.kalshi import _map_market
from app.services.catalog.event_card_models import EventCardMarketSummaryDTO, EventCardSummaryDTO
from app.services.catalog.fixed_point import sum_fp
from app.services.kalshi.rest_client import KalshiRestClient

if TYPE_CHECKING:
    from app.services.debug_metrics import DebugMetrics


@dataclass(frozen=True)
class EventCardSnapshot:
    snapshot_id: str
    built_at: datetime
    cards: list[EventCardSummaryDTO]


async def build_event_card_snapshot(
    client: KalshiRestClient,
    debug_metrics: "DebugMetrics | None" = None,
) -> EventCardSnapshot:
    build_record = debug_metrics.start_snapshot_build() if debug_metrics else None

    cards: list[EventCardSummaryDTO] = []
    cursor: str | None = None

    while True:
        raw = await client.get_events(
            status="open",
            limit=200,
            cursor=cursor,
            with_nested_markets=True,
        )

        page_events = raw.get("events") or []
        for raw_event in page_events:
            cards.append(_build_event_card(raw_event))

        if build_record is not None:
            build_record.pages_fetched += 1
            build_record.events_processed = len(cards)
            build_record.markets_processed = sum(c.market_count for c in cards)

        cursor = raw.get("cursor") or None
        if cursor is None:
            break

    if build_record is not None:
        from datetime import datetime as _dt
        build_record.finished_at = _dt.now(timezone.utc)

    return EventCardSnapshot(
        snapshot_id=str(uuid4()),
        built_at=datetime.now(timezone.utc),
        cards=cards,
    )


def _build_event_card(raw_event: dict) -> EventCardSummaryDTO:
    markets = [_build_market_summary(market) for market in (raw_event.get("markets") or [])]
    ordered_markets = sorted(
        markets,
        key=lambda market: (
            -float(market.volume_fp),
            -float(market.open_interest_fp),
            market.close_time is None,
            market.close_time,
            market.ticker,
        ),
    )
    nearest_close_time = min((market.close_time for market in markets if market.close_time is not None), default=None)

    return EventCardSummaryDTO(
        event_ticker=raw_event["event_ticker"],
        series_ticker=raw_event.get("series_ticker"),
        category=raw_event.get("category"),
        title=raw_event.get("title"),
        sub_title=raw_event.get("sub_title"),
        mutually_exclusive=raw_event.get("mutually_exclusive"),
        last_updated_ts=raw_event.get("last_updated_ts"),
        market_count=len(markets),
        nearest_close_time=nearest_close_time,
        total_volume_fp=sum_fp([market.volume_fp for market in markets]),
        total_open_interest_fp=sum_fp([market.open_interest_fp for market in markets]),
        top_markets=ordered_markets[:2],
    )


def _build_market_summary(raw_market: dict) -> EventCardMarketSummaryDTO:
    market = _map_market(raw_market)
    return EventCardMarketSummaryDTO(
        ticker=market.ticker,
        event_ticker=market.event_ticker,
        market_type=market.market_type,
        yes_sub_title=market.yes_sub_title,
        no_sub_title=market.no_sub_title,
        status=market.status,
        close_time=market.close_time,
        yes_bid_dollars=market.yes_bid_dollars,
        yes_ask_dollars=market.yes_ask_dollars,
        last_price_dollars=market.last_price_dollars,
        volume_fp=sum_fp([market.volume_fp]),
        open_interest_fp=sum_fp([market.open_interest_fp]),
    )