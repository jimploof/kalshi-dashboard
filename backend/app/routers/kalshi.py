"""
GET /api/kalshi/health — authenticated Kalshi connectivity probe.

Internally performs one authenticated REST call to GET /portfolio/balance to
verify credentials and network reachability. The upstream response payload is
intentionally discarded — no account data is returned to callers.

HTTP status codes:
  200  success          — Kalshi authenticated and responded successfully
  503  missing_config   — API key or private key not configured
  502  auth_failure     — Kalshi rejected the request (401 / 403)
  502  upstream_failure — network error or unexpected upstream status
"""

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.dependencies import KalshiClientDep, SettingsDep

logger = logging.getLogger(__name__)
router = APIRouter(tags=["kalshi"])

_SUCCESS_MESSAGE = "Kalshi connectivity and authentication verified via balance probe."
_PROVIDER = "kalshi"
_PROBE = "get_balance"


class KalshiHealthResponse(BaseModel):
    status: Literal["success", "missing_config", "auth_failure", "upstream_failure"]
    message: str
    provider: str
    authenticated: bool
    probe: str
    base_url: str
    environment: str


@router.get("/kalshi/health", response_model=KalshiHealthResponse)
async def kalshi_health(
    client: KalshiClientDep,
    settings: SettingsDep,
    response: Response,
) -> KalshiHealthResponse:
    """Probe authenticated Kalshi REST connectivity via GET /portfolio/balance.

    Returns sanitized connectivity metadata only — no account financial data.
    """
    base_url = settings.kalshi_api_base_url
    environment = settings.kalshi_env

    if not client.is_configured():
        response.status_code = 503
        return KalshiHealthResponse(
            status="missing_config",
            message="Kalshi credentials are not configured.",
            provider=_PROVIDER,
            authenticated=False,
            probe=_PROBE,
            base_url=base_url,
            environment=environment,
        )

    try:
        await client.get_balance()
        return KalshiHealthResponse(
            status="success",
            message=_SUCCESS_MESSAGE,
            provider=_PROVIDER,
            authenticated=True,
            probe=_PROBE,
            base_url=base_url,
            environment=environment,
        )
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (401, 403):
            logger.warning("Kalshi auth failure (HTTP %s)", code)
            response.status_code = 502
            return KalshiHealthResponse(
                status="auth_failure",
                message=f"Kalshi rejected the request with HTTP {code}.",
                provider=_PROVIDER,
                authenticated=False,
                probe=_PROBE,
                base_url=base_url,
                environment=environment,
            )
        logger.warning("Kalshi upstream HTTP error %s at %s", code, exc.request.url)
        response.status_code = 502
        return KalshiHealthResponse(
            status="upstream_failure",
            message=f"Kalshi returned an unexpected HTTP {code} response.",
            provider=_PROVIDER,
            authenticated=False,
            probe=_PROBE,
            base_url=base_url,
            environment=environment,
        )
    except httpx.RequestError as exc:
        logger.warning("Kalshi request error: %s", exc)
        response.status_code = 502
        return KalshiHealthResponse(
            status="upstream_failure",
            message="Could not reach Kalshi API.",
            provider=_PROVIDER,
            authenticated=False,
            probe=_PROBE,
            base_url=base_url,
            environment=environment,
        )
