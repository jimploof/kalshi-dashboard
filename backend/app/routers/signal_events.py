import logging
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.dependencies import DbDep
from app.services.signal_events.store import (
    fetch_signal_events,
    fetch_signal_lifecycle_events,
    insert_signal_event,
    insert_signal_lifecycle_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["signal-events"])


class SignalEventCreateRequest(BaseModel):
    market_ticker: str = Field(min_length=1, max_length=128)
    event_ticker: str | None = Field(default=None, max_length=128)
    mode: Literal["strict", "fast", "open"] = "strict"
    signal_direction: Literal["BUY", "SELL", "WAIT"]
    confidence: int = Field(ge=0, le=100)
    buy_score: int = Field(ge=0, le=100)
    sell_score: int = Field(ge=0, le=100)
    entry_note: str | None = None
    stop_note: str | None = None
    target_note: str | None = None
    conditions_met: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="frontend-market-view", max_length=64)


class SignalEventCreateResponse(BaseModel):
    status: Literal["success", "failed"]
    event_id: int | None = None


class SignalEventDTO(BaseModel):
    id: int
    created_at: datetime
    market_ticker: str
    event_ticker: str | None = None
    mode: Literal["strict", "fast", "open"] = "strict"
    signal_direction: Literal["BUY", "SELL", "WAIT"]
    confidence: int
    buy_score: int
    sell_score: int
    entry_note: str | None = None
    stop_note: str | None = None
    target_note: str | None = None
    conditions_met: dict[str, Any]
    diagnostics: dict[str, Any]
    source: str


class SignalEventsListResponse(BaseModel):
    status: Literal["success", "failed"]
    events: list[SignalEventDTO]


class SignalLifecycleEventCreateRequest(BaseModel):
    market_ticker: str = Field(min_length=1, max_length=128)
    event_ticker: str | None = Field(default=None, max_length=128)
    mode: Literal["strict", "fast", "open"]
    lifecycle_state: Literal[
        "SIGNAL_EMITTED",
        "ENTRY_ARMED",
        "ENTRY_FILLED",
        "POSITION_MANAGE",
        "EXIT_SIGNALLED",
        "EXIT_FILLED",
        "OUTCOME_FINALIZED",
    ]
    signal_direction: Literal["BUY", "SELL", "WAIT"] | None = None
    position_side: Literal["FLAT", "LONG"]
    trigger_price_cents: int | None = None
    elapsed_ms: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="frontend-market-view", max_length=64)


class SignalLifecycleEventDTO(BaseModel):
    id: int
    created_at: datetime
    market_ticker: str
    event_ticker: str | None = None
    mode: Literal["strict", "fast", "open"]
    lifecycle_state: str
    signal_direction: Literal["BUY", "SELL", "WAIT"] | None = None
    position_side: Literal["FLAT", "LONG"]
    trigger_price_cents: int | None = None
    elapsed_ms: int | None = None
    payload: dict[str, Any]
    source: str


class SignalLifecycleEventsListResponse(BaseModel):
    status: Literal["success", "failed"]
    events: list[SignalLifecycleEventDTO]


@router.post("/signal-events", response_model=SignalEventCreateResponse)
async def create_signal_event(payload: SignalEventCreateRequest, db: DbDep) -> SignalEventCreateResponse:
    """Persist a signal trigger/event snapshot for post-trade analysis."""
    try:
        event_id = await insert_signal_event(
            db,
            market_ticker=payload.market_ticker,
            event_ticker=payload.event_ticker,
            mode=payload.mode,
            signal_direction=payload.signal_direction,
            confidence=payload.confidence,
            buy_score=payload.buy_score,
            sell_score=payload.sell_score,
            entry_note=payload.entry_note,
            stop_note=payload.stop_note,
            target_note=payload.target_note,
            conditions_met=payload.conditions_met,
            diagnostics=payload.diagnostics,
            source=payload.source,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to insert signal event: %s", exc)
        return SignalEventCreateResponse(status="failed")

    return SignalEventCreateResponse(status="success", event_id=event_id)


@router.get("/signal-events", response_model=SignalEventsListResponse)
async def list_signal_events(
    db: DbDep,
    market_ticker: str | None = Query(default=None),
    event_ticker: str | None = Query(default=None),
    mode: Literal["strict", "fast", "open"] | None = Query(default=None),
    direction: Literal["BUY", "SELL", "WAIT"] | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
) -> SignalEventsListResponse:
    """Return recent signal events for a market/event with optional filtering."""
    try:
        rows = await fetch_signal_events(
            db,
            market_ticker=market_ticker,
            event_ticker=event_ticker,
            mode=mode,
            direction=direction,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch signal events: %s", exc)
        return SignalEventsListResponse(status="failed", events=[])

    events = [
        SignalEventDTO(
            id=int(row["id"]),
            created_at=row["created_at"],
            market_ticker=row["market_ticker"],
            event_ticker=row["event_ticker"],
            mode=row.get("mode") or "strict",
            signal_direction=row["signal_direction"],
            confidence=int(row["confidence"]),
            buy_score=int(row["buy_score"]),
            sell_score=int(row["sell_score"]),
            entry_note=row["entry_note"],
            stop_note=row["stop_note"],
            target_note=row["target_note"],
            conditions_met=row["conditions_met"] or {},
            diagnostics=row["diagnostics"] or {},
            source=row["source"],
        )
        for row in rows
    ]
    return SignalEventsListResponse(status="success", events=events)


@router.post("/signal-events/lifecycle", response_model=SignalEventCreateResponse)
async def create_signal_lifecycle_event(
    payload: SignalLifecycleEventCreateRequest,
    db: DbDep,
) -> SignalEventCreateResponse:
    """Persist a lifecycle transition event for simulated/real position management."""
    try:
        event_id = await insert_signal_lifecycle_event(
            db,
            market_ticker=payload.market_ticker,
            event_ticker=payload.event_ticker,
            mode=payload.mode,
            lifecycle_state=payload.lifecycle_state,
            signal_direction=payload.signal_direction,
            position_side=payload.position_side,
            trigger_price_cents=payload.trigger_price_cents,
            elapsed_ms=payload.elapsed_ms,
            payload=payload.payload,
            source=payload.source,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to insert signal lifecycle event: %s", exc)
        return SignalEventCreateResponse(status="failed")

    return SignalEventCreateResponse(status="success", event_id=event_id)


@router.get("/signal-events/lifecycle", response_model=SignalLifecycleEventsListResponse)
async def list_signal_lifecycle_events(
    db: DbDep,
    market_ticker: str | None = Query(default=None),
    event_ticker: str | None = Query(default=None),
    mode: Literal["strict", "fast", "open"] | None = Query(default=None),
    lifecycle_state: str | None = Query(default=None),
    limit: int = Query(default=400, ge=1, le=2000),
) -> SignalLifecycleEventsListResponse:
    """Return lifecycle transition history with optional mode/state filters."""
    try:
        rows = await fetch_signal_lifecycle_events(
            db,
            market_ticker=market_ticker,
            event_ticker=event_ticker,
            mode=mode,
            lifecycle_state=lifecycle_state,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch signal lifecycle events: %s", exc)
        return SignalLifecycleEventsListResponse(status="failed", events=[])

    events = [
        SignalLifecycleEventDTO(
            id=int(row["id"]),
            created_at=row["created_at"],
            market_ticker=row["market_ticker"],
            event_ticker=row["event_ticker"],
            mode=row["mode"],
            lifecycle_state=row["lifecycle_state"],
            signal_direction=row["signal_direction"],
            position_side=row["position_side"],
            trigger_price_cents=row["trigger_price_cents"],
            elapsed_ms=row["elapsed_ms"],
            payload=row["payload"] or {},
            source=row["source"],
        )
        for row in rows
    ]
    return SignalLifecycleEventsListResponse(status="success", events=events)
