from datetime import datetime

from app.services.catalog.event_card_models import EventCardSummaryDTO
from app.services.catalog.event_card_page import filter_cards, page_cards, sort_cards


def _card(
    event_ticker: str,
    *,
    category: str,
    series_ticker: str | None,
    title: str,
    total_volume_fp: str,
    total_open_interest_fp: str,
    nearest_close_time: str | None,
) -> EventCardSummaryDTO:
    return EventCardSummaryDTO(
        event_ticker=event_ticker,
        category=category,
        series_ticker=series_ticker,
        title=title,
        sub_title=None,
        mutually_exclusive=None,
        last_updated_ts=None,
        market_count=1,
        nearest_close_time=datetime.fromisoformat(nearest_close_time.replace("Z", "+00:00")) if nearest_close_time else None,
        total_volume_fp=total_volume_fp,
        total_open_interest_fp=total_open_interest_fp,
        top_markets=[],
    )


def test_filter_cards_is_case_insensitive_by_category() -> None:
    cards = [
        _card("E1", category="Sports", series_ticker="KXNBA", title="A", total_volume_fp="1.00", total_open_interest_fp="1.00", nearest_close_time=None),
        _card("E2", category="Crypto", series_ticker="KXBTC", title="B", total_volume_fp="2.00", total_open_interest_fp="2.00", nearest_close_time=None),
    ]

    filtered = filter_cards(cards, "sports", None)

    assert [card.event_ticker for card in filtered] == ["E1"]


def test_sort_cards_total_volume_desc_uses_title_then_ticker_ties() -> None:
    cards = [
        _card("E2", category="Sports", series_ticker=None, title="Beta", total_volume_fp="10.00", total_open_interest_fp="1.00", nearest_close_time=None),
        _card("E1", category="Sports", series_ticker=None, title="Alpha", total_volume_fp="10.00", total_open_interest_fp="1.00", nearest_close_time=None),
    ]

    ordered = sort_cards(cards, "total_volume", "desc")

    assert [card.event_ticker for card in ordered] == ["E1", "E2"]


def test_page_cards_returns_next_offset_until_exhausted() -> None:
    cards = [
        _card(f"E{i}", category="Sports", series_ticker=None, title=str(i), total_volume_fp="1.00", total_open_interest_fp="1.00", nearest_close_time=None)
        for i in range(5)
    ]

    page, next_offset, total = page_cards(cards, 0, 2)

    assert total == 5
    assert len(page) == 2
    assert next_offset == 2