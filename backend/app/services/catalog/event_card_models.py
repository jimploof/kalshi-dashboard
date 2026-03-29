from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EventCardSortBy = Literal["total_volume", "total_open_interest", "nearest_close_time", "title"]
SortOrder = Literal["asc", "desc"]
CatalogEventCardsStatus = Literal["success", "upstream_failure"]


class EventCardMarketSummaryDTO(BaseModel):
    ticker: str
    event_ticker: str | None = None
    market_type: str | None = None
    yes_sub_title: str | None = None
    no_sub_title: str | None = None
    status: str | None = None
    close_time: datetime | None = None
    yes_bid_dollars: str | None = None
    yes_ask_dollars: str | None = None
    last_price_dollars: str | None = None
    volume_fp: str
    open_interest_fp: str


class EventCardSummaryDTO(BaseModel):
    event_ticker: str
    series_ticker: str | None = None
    category: str | None = None
    title: str | None = None
    sub_title: str | None = None
    mutually_exclusive: bool | None = None
    last_updated_ts: datetime | None = None
    market_count: int = Field(ge=0)
    nearest_close_time: datetime | None = None
    total_volume_fp: str
    total_open_interest_fp: str
    top_markets: list[EventCardMarketSummaryDTO] = Field(default_factory=list, max_length=2)


class CatalogEventCardsResponse(BaseModel):
    status: CatalogEventCardsStatus
    cards: list[EventCardSummaryDTO] = Field(default_factory=list)
    next_cursor: str | None = None
    total: int = Field(ge=0)
    snapshot_id: str
    snapshot_built_at: datetime
    stale: bool