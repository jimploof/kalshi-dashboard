"""Debug router — exposes live metrics when DEBUG_MODE=true.

This router is only useful in local development.  The /api/debug/status
endpoint returns a 403 when debug_mode is false so that it is safe to mount
unconditionally; no metrics data is ever exposed in production mode.

Routes:
    GET /api/debug/status — full debug snapshot including build timing,
                            cache state, and recent Kalshi call log.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["debug"])


class DebugStatusResponse(BaseModel):
    debug_mode: bool
    server_time_utc: str
    event_card_refresh_in_progress: bool
    snapshot_metrics: dict[str, Any] | None
    recent_kalshi_calls: list[dict[str, Any]]
    recent_cache_lookups: list[dict[str, Any]]
    snapshot_builds: list[dict[str, Any]]


@router.get("/debug/status", response_model=DebugStatusResponse)
async def get_debug_status(request: Request, response: Response) -> DebugStatusResponse:
    """Return live debug metrics.

    Returns 403 when DEBUG_MODE is not enabled.  No metrics are included in
    the 403 body so that this endpoint reveals nothing about production state.
    """
    settings = get_settings()
    if not settings.debug_mode:
        response.status_code = 403
        return DebugStatusResponse(
            debug_mode=False,
            server_time_utc=datetime.now(timezone.utc).isoformat(),
            event_card_refresh_in_progress=False,
            snapshot_metrics=None,
            recent_kalshi_calls=[],
            recent_cache_lookups=[],
            snapshot_builds=[],
        )

    debug_metrics = getattr(request.app.state, "debug_metrics", None)
    refresh_in_progress: bool = getattr(request.app.state, "event_card_refresh_in_progress", False)

    if debug_metrics is None:
        # debug_mode=true but metrics not initialised yet (very early startup)
        return DebugStatusResponse(
            debug_mode=True,
            server_time_utc=datetime.now(timezone.utc).isoformat(),
            event_card_refresh_in_progress=refresh_in_progress,
            snapshot_metrics=None,
            recent_kalshi_calls=[],
            recent_cache_lookups=[],
            snapshot_builds=[],
        )

    all_metrics = debug_metrics.as_dict()
    current_build = debug_metrics.current_build

    return DebugStatusResponse(
        debug_mode=True,
        server_time_utc=datetime.now(timezone.utc).isoformat(),
        event_card_refresh_in_progress=refresh_in_progress,
        snapshot_metrics=current_build.as_dict() if current_build is not None else None,
        recent_kalshi_calls=all_metrics["recent_kalshi_calls"],
        recent_cache_lookups=all_metrics["recent_cache_lookups"],
        snapshot_builds=all_metrics["snapshot_builds"],
    )
