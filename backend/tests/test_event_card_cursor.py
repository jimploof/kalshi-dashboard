import pytest

from app.services.catalog.event_card_cursor import (
    CursorDecodeError,
    EventCardCursorContext,
    decode_cursor,
    encode_cursor,
    validate_cursor_context,
)


def test_cursor_round_trip() -> None:
    context = EventCardCursorContext(
        snapshot_id="snap-1",
        category="Sports",
        series_ticker="KXNBA",
        sort_by="total_volume",
        sort_order="desc",
    )

    cursor = encode_cursor(context, 24)
    decoded, offset = decode_cursor(cursor)

    assert decoded == context
    assert offset == 24


def test_decode_cursor_rejects_malformed_payload() -> None:
    with pytest.raises(CursorDecodeError):
        decode_cursor("not-base64")


def test_validate_cursor_context_requires_exact_match() -> None:
    current = EventCardCursorContext(
        snapshot_id="snap-1",
        category="Sports",
        series_ticker=None,
        sort_by="total_volume",
        sort_order="desc",
    )
    mismatched = EventCardCursorContext(
        snapshot_id="snap-1",
        category="Crypto",
        series_ticker=None,
        sort_by="total_volume",
        sort_order="desc",
    )

    assert validate_cursor_context(current, current) is True
    assert validate_cursor_context(mismatched, current) is False