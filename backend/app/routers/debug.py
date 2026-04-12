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


class ConnectivityStatus(BaseModel):
    rest_url: str
    rest_configured: bool
    rest_status: str  # 'active', 'error', 'no_calls'
    rest_last_call_at: str | None
    rest_last_status_code: int | None
    ws_url: str
    ws_configured: bool
    ws_connected: bool
    ws_subscribed_tickers: list[str]
    ws_frontend_clients: dict[str, int]


class DebugStatusResponse(BaseModel):
    debug_mode: bool
    server_time_utc: str
    connectivity: ConnectivityStatus | None
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
            connectivity=None,
            event_card_refresh_in_progress=False,
            snapshot_metrics=None,
            recent_kalshi_calls=[],
            recent_cache_lookups=[],
            snapshot_builds=[],
        )

    debug_metrics = getattr(request.app.state, "debug_metrics", None)
    refresh_in_progress: bool = getattr(request.app.state, "event_card_refresh_in_progress", False)

    # ── Build connectivity status ─────────────────────────────────────────
    ws_manager = getattr(request.app.state, "ws_manager", None)
    ws_info = ws_manager.connectivity_status() if ws_manager is not None else None

    # Determine REST status from recent call history.
    rest_status = "no_calls"
    rest_last_call_at: str | None = None
    rest_last_status_code: int | None = None
    if debug_metrics is not None:
        calls = debug_metrics.as_dict()["recent_kalshi_calls"]
        if calls:
            latest = calls[0]  # already sorted newest-first
            rest_last_call_at = latest["finished_at"] or latest["started_at"]
            rest_last_status_code = latest["status_code"]
            rest_status = "active" if latest["error"] is None and latest["status_code"] == 200 else "error"

    connectivity = ConnectivityStatus(
        rest_url=settings.kalshi_api_base_url,
        rest_configured=bool(settings.kalshi_api_key_id) and bool(settings.kalshi_private_key_path),
        rest_status=rest_status,
        rest_last_call_at=rest_last_call_at,
        rest_last_status_code=rest_last_status_code,
        ws_url=ws_info["url"] if ws_info else settings.kalshi_ws_url,
        ws_configured=ws_info["configured"] if ws_info else False,
        ws_connected=ws_info["connected"] if ws_info else False,
        ws_subscribed_tickers=ws_info["subscribed_tickers"] if ws_info else [],
        ws_frontend_clients=ws_info["frontend_clients"] if ws_info else {},
    )

    if debug_metrics is None:
        return DebugStatusResponse(
            debug_mode=True,
            server_time_utc=datetime.now(timezone.utc).isoformat(),
            connectivity=connectivity,
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
        connectivity=connectivity,
        event_card_refresh_in_progress=refresh_in_progress,
        snapshot_metrics=current_build.as_dict() if current_build is not None else None,
        recent_kalshi_calls=all_metrics["recent_kalshi_calls"],
        recent_cache_lookups=all_metrics["recent_cache_lookups"],
        snapshot_builds=all_metrics["snapshot_builds"],
    )
