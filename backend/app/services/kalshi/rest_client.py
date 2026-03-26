"""
Thin async REST client for authenticated Kalshi API requests.

This module owns:
  - private key loading
  - auth header construction (timestamp + signature)
  - single-method GET /portfolio/balance probe call

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
