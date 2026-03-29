from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import redis.asyncio as aioredis

from app.services.catalog.event_card_models import EventCardSummaryDTO
from app.services.catalog.event_card_snapshot import EventCardSnapshot

if TYPE_CHECKING:
    from app.services.debug_metrics import DebugMetrics

logger = logging.getLogger(__name__)

_EVENT_CARD_SNAPSHOT_KEY = "catalog:event-cards:open:snapshot"


async def get_event_card_snapshot(
    redis: aioredis.Redis,
    debug_metrics: "DebugMetrics | None" = None,
) -> EventCardSnapshot | None:
    try:
        cached = await redis.get(_EVENT_CARD_SNAPSHOT_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis GET %s failed: %s", _EVENT_CARD_SNAPSHOT_KEY, exc)
        if debug_metrics is not None:
            debug_metrics.record_cache_lookup(hit=False)
        return None

    if cached is None:
        if debug_metrics is not None:
            debug_metrics.record_cache_lookup(hit=False)
        return None

    try:
        payload = json.loads(cached)
        snapshot = EventCardSnapshot(
            snapshot_id=payload["snapshot_id"],
            built_at=datetime.fromisoformat(payload["built_at"]),
            cards=[EventCardSummaryDTO(**card) for card in payload.get("cards") or []],
        )
        if debug_metrics is not None:
            age = (datetime.now(timezone.utc) - snapshot.built_at).total_seconds()
            debug_metrics.record_cache_lookup(
                hit=True,
                snapshot_id=snapshot.snapshot_id,
                snapshot_age_seconds=age,
                was_stale=age > 120,
                was_discarded=age > 900,
            )
        return snapshot
    except Exception as exc:  # noqa: BLE001
        logger.warning("Event-card snapshot cache corrupt; ignoring: %s", exc)
        if debug_metrics is not None:
            debug_metrics.record_cache_lookup(hit=False)
        return None


async def set_event_card_snapshot(
    redis: aioredis.Redis,
    snapshot: EventCardSnapshot,
    ttl_seconds: int = 900,
) -> None:
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "built_at": snapshot.built_at.isoformat(),
        "cards": [card.model_dump(mode="json") for card in snapshot.cards],
    }
    try:
        await redis.set(_EVENT_CARD_SNAPSHOT_KEY, json.dumps(payload), ex=ttl_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis SET %s failed: %s", _EVENT_CARD_SNAPSHOT_KEY, exc)


def get_event_card_snapshot_age(snapshot: EventCardSnapshot, now: datetime) -> timedelta:
    return now - snapshot.built_at


def is_snapshot_stale(
    snapshot: EventCardSnapshot,
    now: datetime,
    stale_after_seconds: int = 120,
) -> bool:
    return get_event_card_snapshot_age(snapshot, now) > timedelta(seconds=stale_after_seconds)


def should_discard_snapshot(
    snapshot: EventCardSnapshot,
    now: datetime,
    max_age_seconds: int = 900,
) -> bool:
    return get_event_card_snapshot_age(snapshot, now) > timedelta(seconds=max_age_seconds)


def current_utc_time() -> datetime:
    return datetime.now(timezone.utc)