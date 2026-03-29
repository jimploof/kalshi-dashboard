from __future__ import annotations

from app.services.catalog.event_card_models import EventCardSortBy, EventCardSummaryDTO, SortOrder
from app.services.catalog.fixed_point import parse_fp


def filter_cards(
    cards: list[EventCardSummaryDTO],
    category: str,
    series_ticker: str | None,
) -> list[EventCardSummaryDTO]:
    category_lower = category.lower()
    filtered = [card for card in cards if (card.category or "").lower() == category_lower]
    if series_ticker is not None:
        filtered = [card for card in filtered if card.series_ticker == series_ticker]
    return filtered


def sort_cards(
    cards: list[EventCardSummaryDTO],
    sort_by: EventCardSortBy,
    sort_order: SortOrder,
) -> list[EventCardSummaryDTO]:
    ordered = sorted(cards, key=lambda card: card.event_ticker)
    ordered = sorted(ordered, key=lambda card: (card.title or "").lower())

    reverse = sort_order == "desc"
    if sort_by == "total_volume":
        return sorted(ordered, key=lambda card: parse_fp(card.total_volume_fp), reverse=reverse)
    if sort_by == "total_open_interest":
        return sorted(ordered, key=lambda card: parse_fp(card.total_open_interest_fp), reverse=reverse)
    if sort_by == "title":
        return sorted(ordered, key=lambda card: (card.title or "").lower(), reverse=reverse)

    def close_key(card: EventCardSummaryDTO) -> tuple[int, float]:
        close_time = card.nearest_close_time
        if close_time is None:
            return (1, 0.0)
        timestamp = close_time.timestamp()
        return (0, -timestamp if reverse else timestamp)

    return sorted(ordered, key=close_key)


def page_cards(
    cards: list[EventCardSummaryDTO],
    offset: int,
    limit: int,
) -> tuple[list[EventCardSummaryDTO], int | None, int]:
    total = len(cards)
    page = cards[offset: offset + limit]
    next_offset = offset + limit
    return page, (next_offset if next_offset < total else None), total