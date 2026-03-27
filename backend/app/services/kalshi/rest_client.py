"""
Thin async REST client for authenticated Kalshi API requests.

This module owns:
  - private key loading
  - auth header construction (timestamp + signature)
  - all Kalshi REST calls used by backend routes

Public methods:
  get_balance()   — GET /portfolio/balance (authenticated probe)
  get_markets()   — GET /markets           (market list / discovery)
  get_market()    — GET /markets/{ticker}  (single market detail)
  get_events()    — GET /events            (event list / discovery)
  get_event()     — GET /events/{ticker}   (single event detail)
  get_series()    — GET /series            (series list / navigation)

All Kalshi REST access in the backend routes through this client.
"""

import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from app.config import Settings
from app.services.kalshi.signing import current_timestamp_ms, sign_request

logger = logging.getLogger(__name__)


class KalshiRestClient:
    """Authenticated Kalshi REST client (read-only probe scope for this slice)."""

    def __init__(self, settings: Settings) -> None:
        self._api_base_url: str = settings.kalshi_api_base_url
        self._api_key_id: str | None = settings.kalshi_api_key_id
        self._private_key: RSAPrivateKey | None = self._load_key(
            settings.kalshi_private_key_path
        )

    # ------------------------------------------------------------------
    # Configuration check
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return True only when all required Kalshi credentials are present."""
        return bool(self._api_key_id) and self._private_key is not None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_key(path: str | None) -> RSAPrivateKey | None:
        if not path:
            return None
        try:
            key_bytes = Path(path).read_bytes()
        except IsADirectoryError:
            logger.error(
                "Kalshi private key path %r is a directory, not a file. "
                "Docker likely created it automatically because the source file "
                "did not exist when the container started. Place the real .key "
                "file there and restart the container.",
                path,
            )
            return None
        except OSError as exc:
            logger.error("Cannot read Kalshi private key at %r: %s", path, exc)
            return None
        try:
            key = serialization.load_pem_private_key(key_bytes, password=None)
            if not isinstance(key, RSAPrivateKey):
                logger.error("Kalshi key at %r is not an RSA private key", path)
                return None
            return key
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to parse Kalshi private key at %r: %s", path, exc)
            return None

    def _auth_headers(self, method: str, endpoint: str) -> dict[str, str]:
        """
        Build the three required Kalshi auth headers.

        The signing path is derived from the full URL so that it includes the
        /trade-api/v2 prefix as required by the signing spec.
        Ref: https://docs.kalshi.com/getting_started/api_keys
        """
        # urlparse gives us the path component of the full URL, e.g.
        # "https://demo-api.kalshi.co/trade-api/v2/portfolio/balance"
        # → "/trade-api/v2/portfolio/balance"
        sign_path = urlparse(self._api_base_url + endpoint).path
        ts = current_timestamp_ms()
        sig = sign_request(
            self._private_key,  # type: ignore[arg-type]  # guarded by is_configured()
            ts,
            method,
            sign_path,
        )
        return {
            "KALSHI-ACCESS-KEY": self._api_key_id,  # type: ignore[return-value]
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig,
        }

    # ------------------------------------------------------------------
    # Public API surface (probe only for this slice)
    # ------------------------------------------------------------------

    async def get_balance(self) -> dict[str, int]:
        """
        GET /portfolio/balance — authenticated probe endpoint.

        Returns the raw Kalshi response dict with keys:
          balance (int, cents), portfolio_value (int, cents), updated_ts (int, unix ms)

        Raises:
            httpx.HTTPStatusError: on non-2xx responses (caller inspects status code).
            httpx.RequestError:    on network/timeout errors.
        """
        endpoint = "/portfolio/balance"
        headers = self._auth_headers("GET", endpoint)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self._api_base_url + endpoint,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def get_markets(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict:
        """
        GET /markets — public market discovery endpoint.

        Returns the raw Kalshi response dict with keys:
          markets (list of market objects), cursor (str, pagination)

        Auth headers are included when credentials are configured; the Kalshi
        /markets endpoint is public and works without auth, but providing auth
        avoids unauthenticated rate-limit buckets.

        Raises:
            httpx.HTTPStatusError: on non-2xx responses (caller inspects status code).
            httpx.RequestError:    on network/timeout errors.
        """
        endpoint = "/markets"
        params: dict[str, str | int] = {"limit": limit}
        if status is not None:
            params["status"] = status
        if cursor is not None:
            params["cursor"] = cursor

        headers = self._auth_headers("GET", endpoint) if self.is_configured() else {}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self._api_base_url + endpoint,
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def get_market(self, ticker: str) -> dict:
        """
        GET /markets/{ticker} — single market detail by ticker.

        Returns the raw Kalshi response dict with key:
          market (object with the full documented market schema)

        Auth headers are sent when credentials are configured; the Kalshi
        /markets endpoint is publicly accessible without auth.

        Raises:
            httpx.HTTPStatusError: on non-2xx responses (caller inspects status code).
            httpx.RequestError:    on network/timeout errors.
        """
        endpoint = f"/markets/{ticker}"
        headers = self._auth_headers("GET", endpoint) if self.is_configured() else {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self._api_base_url + endpoint,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def get_events(
        self,
        *,
        series_ticker: str | None = None,
        status: str | None = None,
        limit: int = 200,
        cursor: str | None = None,
        with_nested_markets: bool = False,
        min_close_ts: int | None = None,
        min_updated_ts: int | None = None,
    ) -> dict:
        """
        GET /events — public event discovery endpoint.

        An event represents a real-world occurrence containing one or more
        markets (e.g. "Will Bitcoin close above $30k on March 1?").  Events
        group related markets and carry the category field used for
        domain-level navigation (crypto, politics, sports, etc.).

        Returns the raw Kalshi response dict with keys:
          events (list of event objects), cursor (str, pagination)

        When with_nested_markets=True each event object also contains a
        'markets' list — this is the recommended way to load an event and
        its related markets in a single round-trip.

        Documented optional filters (confirmed from docs.kalshi.com/api-reference/events/get-events):
          series_ticker  — filter by series
          status         — unopened | open | closed | settled
          min_close_ts   — Unix seconds; events with at least one market closing after this time
          min_updated_ts — Unix seconds; events updated after this time (efficient polling)

        Auth headers are sent when credentials are configured; the Kalshi
        /events endpoint is public and works without auth.

        Raises:
            httpx.HTTPStatusError: on non-2xx responses (caller inspects status code).
            httpx.RequestError:    on network/timeout errors.
        """
        endpoint = "/events"
        params: dict[str, str | int | bool] = {"limit": limit}
        if series_ticker is not None:
            params["series_ticker"] = series_ticker
        if status is not None:
            params["status"] = status
        if cursor is not None:
            params["cursor"] = cursor
        if with_nested_markets:
            params["with_nested_markets"] = "true"
        if min_close_ts is not None:
            params["min_close_ts"] = min_close_ts
        if min_updated_ts is not None:
            params["min_updated_ts"] = min_updated_ts

        headers = self._auth_headers("GET", endpoint) if self.is_configured() else {}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self._api_base_url + endpoint,
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def get_event(
        self,
        event_ticker: str,
        *,
        with_nested_markets: bool = True,
    ) -> dict:
        """
        GET /events/{event_ticker} — single event lookup by ticker.

        Returns the raw Kalshi response dict with keys:
          event (object), markets (list, deprecated top-level field)

        By default requests with_nested_markets=true so that the event object
        itself contains the markets list, matching the canonical usage pattern
        for the workstation "related markets" panel.

        The upstream also returns a deprecated top-level ``markets`` field;
        we use only ``event.markets`` (when with_nested_markets=True) in the
        normalization layer and ignore the top-level duplicate.

        Auth headers are sent when credentials are configured; the endpoint is
        publicly accessible without auth.

        Raises:
            httpx.HTTPStatusError: on non-2xx responses (caller inspects status code).
            httpx.RequestError:    on network/timeout errors.
        """
        endpoint = f"/events/{event_ticker}"
        params: dict[str, str] = {}
        if with_nested_markets:
            params["with_nested_markets"] = "true"

        headers = self._auth_headers("GET", endpoint) if self.is_configured() else {}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self._api_base_url + endpoint,
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def get_series(
        self,
        *,
        category: str | None = None,
        tags: str | None = None,
    ) -> dict:
        """
        GET /series — public series list endpoint.

        A series is a template for recurring events (e.g. "Monthly Jobs Report",
        "Daily Bitcoin Price").  Series carry category and tags, making them the
        primary surface for category-level navigation in the workstation.

        Returns the raw Kalshi response dict with key:
          series (list of series objects)

        Note: this endpoint has no pagination cursor in the documented response.
        All matching series are returned in a single response.

        Auth headers are sent when credentials are configured; the endpoint is
        publicly accessible without auth.

        Raises:
            httpx.HTTPStatusError: on non-2xx responses (caller inspects status code).
            httpx.RequestError:    on network/timeout errors.
        """
        endpoint = "/series"
        params: dict[str, str] = {}
        if category is not None:
            params["category"] = category
        if tags is not None:
            params["tags"] = tags

        headers = self._auth_headers("GET", endpoint) if self.is_configured() else {}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self._api_base_url + endpoint,
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
