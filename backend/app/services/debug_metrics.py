"""
In-process debug metrics store.

A single ``DebugMetrics`` instance is attached to ``app.state.debug_metrics``
at startup when ``DEBUG_MODE=true``.  All instrumented code writes to it;
the ``/api/debug/status`` route reads from it.

This module has zero impact on production paths:
  - only instantiated when DEBUG_MODE is true
  - all write helpers are no-ops when the object is absent from app.state
  - no locks needed — the asyncio event loop is single-threaded
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SnapshotBuildRecord:
    """One completed (or in-progress) snapshot build attempt."""

    started_at: datetime
    finished_at: datetime | None = None
    pages_fetched: int = 0
    events_processed: int = 0
    markets_processed: int = 0
    error: str | None = None

    @property
    def elapsed_seconds(self) -> float | None:
        end = self.finished_at or _utcnow()
        return (end - self.started_at).total_seconds()

    @property
    def in_progress(self) -> bool:
        return self.finished_at is None and self.error is None

    def as_dict(self) -> dict:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "elapsed_seconds": round(self.elapsed_seconds or 0, 3),
            "in_progress": self.in_progress,
            "pages_fetched": self.pages_fetched,
            "events_processed": self.events_processed,
            "markets_processed": self.markets_processed,
            "error": self.error,
        }


@dataclass
class KalshiCallRecord:
    """One upstream Kalshi REST call."""

    endpoint: str
    started_at: datetime
    finished_at: datetime | None = None
    status_code: int | None = None
    error: str | None = None

    @property
    def elapsed_ms(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds() * 1000

    def as_dict(self) -> dict:
        return {
            "endpoint": self.endpoint,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "elapsed_ms": round(self.elapsed_ms or 0, 1) if self.elapsed_ms is not None else None,
            "status_code": self.status_code,
            "error": self.error,
        }


@dataclass
class CacheLookupRecord:
    """One Redis cache get for the event-card snapshot."""

    timestamp: datetime
    hit: bool
    snapshot_id: str | None
    snapshot_age_seconds: float | None
    was_stale: bool
    was_discarded: bool

    def as_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "hit": self.hit,
            "snapshot_id": self.snapshot_id,
            "snapshot_age_seconds": round(self.snapshot_age_seconds, 1) if self.snapshot_age_seconds is not None else None,
            "was_stale": self.was_stale,
            "was_discarded": self.was_discarded,
        }


class DebugMetrics:
    """Mutable in-process metrics store written to during request handling."""

    # Keep at most this many records to avoid unbounded memory growth.
    MAX_SNAPSHOT_BUILDS = 10
    MAX_KALSHI_CALLS = 50
    MAX_CACHE_LOOKUPS = 50

    def __init__(self) -> None:
        self._snapshot_builds: list[SnapshotBuildRecord] = []
        self._kalshi_calls: list[KalshiCallRecord] = []
        self._cache_lookups: list[CacheLookupRecord] = []

    # ── Snapshot build tracking ───────────────────────────────────────────

    def start_snapshot_build(self) -> SnapshotBuildRecord:
        record = SnapshotBuildRecord(started_at=_utcnow())
        self._snapshot_builds.append(record)
        if len(self._snapshot_builds) > self.MAX_SNAPSHOT_BUILDS:
            self._snapshot_builds.pop(0)
        return record

    # ── Kalshi call tracking ──────────────────────────────────────────────

    def start_kalshi_call(self, endpoint: str) -> KalshiCallRecord:
        record = KalshiCallRecord(endpoint=endpoint, started_at=_utcnow())
        self._kalshi_calls.append(record)
        if len(self._kalshi_calls) > self.MAX_KALSHI_CALLS:
            self._kalshi_calls.pop(0)
        return record

    # ── Cache lookup tracking ─────────────────────────────────────────────

    def record_cache_lookup(
        self,
        *,
        hit: bool,
        snapshot_id: str | None = None,
        snapshot_age_seconds: float | None = None,
        was_stale: bool = False,
        was_discarded: bool = False,
    ) -> None:
        record = CacheLookupRecord(
            timestamp=_utcnow(),
            hit=hit,
            snapshot_id=snapshot_id,
            snapshot_age_seconds=snapshot_age_seconds,
            was_stale=was_stale,
            was_discarded=was_discarded,
        )
        self._cache_lookups.append(record)
        if len(self._cache_lookups) > self.MAX_CACHE_LOOKUPS:
            self._cache_lookups.pop(0)

    # ── Read-out ──────────────────────────────────────────────────────────

    @property
    def current_build(self) -> SnapshotBuildRecord | None:
        """The most recent snapshot build, whether in-progress or completed."""
        return self._snapshot_builds[-1] if self._snapshot_builds else None

    def as_dict(self) -> dict:
        return {
            "snapshot_builds": [r.as_dict() for r in reversed(self._snapshot_builds)],
            "recent_kalshi_calls": [r.as_dict() for r in reversed(self._kalshi_calls)],
            "recent_cache_lookups": [r.as_dict() for r in reversed(self._cache_lookups)],
        }
