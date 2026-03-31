"""
Kalshi WebSocket v2 manager.

Maintains a single authenticated backend connection to the Kalshi WebSocket
endpoint, manages per-market subscriptions, and fans out channel messages to
subscribed FastAPI WebSocket clients.

Connection lifecycle
--------------------
- ``start()`` launches a background asyncio task that connects to Kalshi and
  handles reconnection with exponential back-off.
- ``stop()`` signals shutdown, cancels the task, and closes the Kalshi socket.

Subscription model
------------------
- Frontend clients connect to the FastAPI WS endpoint ``/ws/market/{ticker}``.
- The endpoint calls ``subscribe_client(ticker, fastapi_ws)`` to register the
  client and, if this is the first subscriber for that ticker, sends a Kalshi
  subscribe command.
- On disconnect the endpoint calls ``unsubscribe_client(ticker, fastapi_ws)``.
  When the last subscriber for a ticker leaves, the Kalshi unsubscribe command
  is sent so we stop receiving data for that market.
- If the Kalshi connection drops and reconnects, the manager automatically
  re-subscribes all currently active tickers.

Authentication
--------------
The Kalshi WS v2 API uses the same RSA-PSS signing scheme as the REST API.
Auth headers are sent as HTTP upgrade headers when establishing the WS
connection:
  KALSHI-ACCESS-KEY       — API key ID
  KALSHI-ACCESS-TIMESTAMP — millisecond UTC epoch
  KALSHI-ACCESS-SIGNATURE — base64-encoded RSA-PSS signature over
                            ``{timestamp}GET{ws_path}``

References
----------
docs.kalshi.com/api-reference/websockets
"""

import asyncio
import json
import logging
from pathlib import Path
from urllib.parse import urlparse

import websockets
import websockets.exceptions
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import WebSocket

from app.config import Settings
from app.services.kalshi.signing import current_timestamp_ms, sign_request

logger = logging.getLogger(__name__)


class KalshiWsManager:
    """Backend-owned authenticated connection to the Kalshi WebSocket v2 API.

    One instance is held on ``app.state.ws_manager`` and shared across all
    request handlers.  All access is from a single asyncio event loop so no
    threading locks are needed for the subscription dictionaries.
    """

    def __init__(self, settings: Settings) -> None:
        self._ws_url: str = settings.kalshi_ws_url
        self._api_key_id: str | None = settings.kalshi_api_key_id
        self._private_key: RSAPrivateKey | None = self._load_key(
            settings.kalshi_private_key_path
        )

        # ticker → set of FastAPI WebSocket objects (frontend clients)
        self._subscriptions: dict[str, set[WebSocket]] = {}

        # Tickers currently subscribed on the Kalshi side for the active session.
        # Cleared on each reconnect — re-populated during _run_session startup.
        self._kalshi_subscribed: set[str] = set()

        # Active Kalshi WS connection (websockets library ClientConnection).
        # None when not connected.
        self._kalshi_ws: websockets.ClientConnection | None = None

        # Serialise outbound Kalshi sends in case multiple callers fire concurrently.
        self._send_lock = asyncio.Lock()

        # Command ID counter (monotonically increasing, resets on restart).
        self._cmd_id: int = 0

        # Signals the background task to stop.
        self._stop_event: asyncio.Event = asyncio.Event()
        self._reader_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch the background connection loop."""
        self._stop_event.clear()
        self._reader_task = asyncio.create_task(
            self._connection_loop(), name="kalshi-ws-manager"
        )
        logger.info("Kalshi WS manager started.")

    async def stop(self) -> None:
        """Signal shutdown, cancel the background task, close the socket."""
        self._stop_event.set()

        # Close the Kalshi socket so the reader loop unblocks.
        ws = self._kalshi_ws
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._kalshi_ws = None

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._reader_task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._reader_task = None

        logger.info("Kalshi WS manager stopped.")

    # ------------------------------------------------------------------
    # Public subscription API (called from WS route handlers)
    # ------------------------------------------------------------------

    async def subscribe_client(self, ticker: str, client_ws: WebSocket) -> None:
        """Register ``client_ws`` as a subscriber for ``ticker``.

        If this is the first subscriber for this ticker AND we have an active
        Kalshi connection, the subscribe command is sent immediately.  If the
        connection is not yet established, the ticker will be subscribed
        automatically when ``_run_session`` next connects.
        """
        if ticker not in self._subscriptions:
            self._subscriptions[ticker] = set()

        self._subscriptions[ticker].add(client_ws)

        # Send Kalshi subscribe only if connected and not already subscribed.
        if (
            self._kalshi_ws is not None
            and ticker not in self._kalshi_subscribed
        ):
            await self._send_subscribe([ticker])

    async def unsubscribe_client(self, ticker: str, client_ws: WebSocket) -> None:
        """Remove ``client_ws`` from the subscriber set for ``ticker``.

        When the last subscriber leaves, an unsubscribe command is sent to
        Kalshi to stop receiving data for that market.
        """
        ticker_set = self._subscriptions.get(ticker)
        if ticker_set is None:
            return

        ticker_set.discard(client_ws)

        if not ticker_set:
            del self._subscriptions[ticker]
            await self._send_unsubscribe([ticker])

    # ------------------------------------------------------------------
    # Internal connection loop
    # ------------------------------------------------------------------

    async def _connection_loop(self) -> None:
        """Outer reconnect loop: connect → read → reconnect on error."""
        base_delay = 1.0
        max_delay = 30.0
        delay = base_delay

        while not self._stop_event.is_set():
            try:
                await self._run_session()
                delay = base_delay  # reset after a clean session
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Kalshi WS session ended: %s — reconnecting in %.1fs", exc, delay
                )

            if self._stop_event.is_set():
                break

            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

    async def _run_session(self) -> None:
        """Single WS session: connect, resubscribe active tickers, read messages."""
        if not self.is_configured():
            logger.info("Kalshi WS credentials not configured — will retry in 60s.")
            await asyncio.sleep(60)
            return

        headers = self._auth_headers()
        try:
            async with websockets.connect(
                self._ws_url, additional_headers=headers
            ) as ws:
                self._kalshi_ws = ws
                self._kalshi_subscribed.clear()
                logger.info("Kalshi WS connected to %s", self._ws_url)

                # Re-subscribe to all tickers that currently have frontend clients.
                active_tickers = list(self._subscriptions.keys())
                if active_tickers:
                    await self._send_subscribe(active_tickers, ws)

                try:
                    async for raw_message in ws:
                        if self._stop_event.is_set():
                            break
                        if isinstance(raw_message, str):
                            await self._dispatch_message(raw_message)
                except websockets.exceptions.ConnectionClosedError as exc:
                    logger.info("Kalshi WS connection closed: %s", exc)
        finally:
            self._kalshi_ws = None
            self._kalshi_subscribed.clear()

    # ------------------------------------------------------------------
    # Kalshi command helpers
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return True when RSA credentials are available."""
        return bool(self._api_key_id) and self._private_key is not None

    def _auth_headers(self) -> dict[str, str]:
        """Build the three required Kalshi WS auth headers."""
        ws_path = urlparse(self._ws_url).path  # e.g. /trade-api/ws/v2
        ts = current_timestamp_ms()
        sig = sign_request(
            self._private_key,  # type: ignore[arg-type]  # guarded by is_configured()
            ts,
            "GET",
            ws_path,
        )
        return {
            "KALSHI-ACCESS-KEY": self._api_key_id,  # type: ignore[return-value]
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig,
        }

    async def _send_subscribe(
        self, tickers: list[str], ws: websockets.ClientConnection | None = None
    ) -> None:
        """Send a subscribe command to Kalshi for the given market tickers."""
        target = ws or self._kalshi_ws
        if target is None or not tickers:
            return

        self._cmd_id += 1
        cmd = {
            "id": self._cmd_id,
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta", "ticker"],
                "market_tickers": tickers,
            },
        }
        try:
            async with self._send_lock:
                await target.send(json.dumps(cmd))
            for t in tickers:
                self._kalshi_subscribed.add(t)
            logger.debug("Kalshi WS subscribed: %s", tickers)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to send Kalshi subscribe command: %s", exc)

    async def _send_unsubscribe(self, tickers: list[str]) -> None:
        """Send an unsubscribe command to Kalshi for the given market tickers."""
        ws = self._kalshi_ws
        if ws is None or not tickers:
            return

        self._cmd_id += 1
        cmd = {
            "id": self._cmd_id,
            "cmd": "unsubscribe",
            "params": {
                "channels": ["orderbook_delta", "ticker"],
                "market_tickers": tickers,
            },
        }
        try:
            async with self._send_lock:
                await ws.send(json.dumps(cmd))
            for t in tickers:
                self._kalshi_subscribed.discard(t)
            logger.debug("Kalshi WS unsubscribed: %s", tickers)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to send Kalshi unsubscribe command: %s", exc)

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    async def _dispatch_message(self, raw: str) -> None:
        """Parse a Kalshi WS message and fan-out to relevant frontend clients.

        Kalshi WS v2 message schema:
          {"type": "ticker"|"orderbook_snapshot"|"orderbook_delta"|"subscribed"|...,
           "sid": <int>, "seq": <int>, "msg": {..."market_ticker": "..."}}
        """
        try:
            msg: dict = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type")

        # Confirmation and system messages are not relayed to clients.
        if msg_type in ("subscribed", "unsubscribed", "error"):
            if msg_type == "error":
                logger.error("Kalshi WS error message received: %s", msg)
            return

        msg_body = msg.get("msg") or {}
        ticker = msg_body.get("market_ticker")
        if not ticker:
            return

        subscribers = self._subscriptions.get(ticker)
        if not subscribers:
            return

        # Fan-out to all subscribed frontend WebSocket connections.
        dead: list[WebSocket] = []
        for client_ws in list(subscribers):
            try:
                await client_ws.send_json(msg)
            except Exception:  # noqa: BLE001
                dead.append(client_ws)

        for ws in dead:
            subscribers.discard(ws)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_key(path: str | None) -> RSAPrivateKey | None:
        """Load the RSA private key from disk.  Returns None on any failure."""
        if not path:
            return None
        try:
            key_bytes = Path(path).read_bytes()
        except Exception as exc:  # noqa: BLE001
            logger.error("Cannot read Kalshi private key for WS at %r: %s", path, exc)
            return None
        try:
            key = serialization.load_pem_private_key(key_bytes, password=None)
            if not isinstance(key, RSAPrivateKey):
                logger.error("WS key at %r is not an RSA private key.", path)
                return None
            return key
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to parse Kalshi WS private key at %r: %s", path, exc)
            return None
