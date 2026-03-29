from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from app.services.catalog.event_card_models import EventCardSortBy, SortOrder


class CursorDecodeError(ValueError):
    pass


@dataclass(frozen=True)
class EventCardCursorContext:
    snapshot_id: str
    category: str
    series_ticker: str | None
    sort_by: EventCardSortBy
    sort_order: SortOrder


def encode_cursor(context: EventCardCursorContext, offset: int) -> str:
    payload = {
        "sid": context.snapshot_id,
        "off": offset,
        "cat": context.category,
        "ser": context.series_ticker,
        "sb": context.sort_by,
        "so": context.sort_order,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> tuple[EventCardCursorContext, int]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise CursorDecodeError("Malformed cursor") from exc

    required = {"sid", "off", "cat", "ser", "sb", "so"}
    if set(payload.keys()) != required:
        raise CursorDecodeError("Cursor payload missing required keys")

    offset = payload["off"]
    if not isinstance(offset, int) or offset < 0:
        raise CursorDecodeError("Cursor offset must be a non-negative integer")

    context = EventCardCursorContext(
        snapshot_id=_require_str(payload["sid"], "snapshot_id"),
        category=_require_str(payload["cat"], "category"),
        series_ticker=_require_optional_str(payload["ser"], "series_ticker"),
        sort_by=_require_sort_by(payload["sb"]),
        sort_order=_require_sort_order(payload["so"]),
    )
    return context, offset


def validate_cursor_context(decoded: EventCardCursorContext, current: EventCardCursorContext) -> bool:
    return decoded == current


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CursorDecodeError(f"Cursor field {field_name} must be a non-empty string")
    return value


def _require_optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise CursorDecodeError(f"Cursor field {field_name} must be null or a non-empty string")
    return value


def _require_sort_by(value: object) -> EventCardSortBy:
    if value not in {"total_volume", "total_open_interest", "nearest_close_time", "title"}:
        raise CursorDecodeError("Cursor sort_by is invalid")
    return value


def _require_sort_order(value: object) -> SortOrder:
    if value not in {"asc", "desc"}:
        raise CursorDecodeError("Cursor sort_order is invalid")
    return value