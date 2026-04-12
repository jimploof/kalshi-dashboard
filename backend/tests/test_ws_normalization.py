"""Tests for KalshiWsManager WS message normalization.

Verifies that raw Kalshi WS payloads are correctly normalized into the
internal DTO contract before being relayed to frontend clients.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.kalshi.ws_manager import KalshiWsManager


@pytest.fixture
def manager() -> KalshiWsManager:
    """Create a KalshiWsManager with mocked settings."""
    settings = MagicMock()
    settings.kalshi_ws_url = "wss://example.com/ws"
    settings.kalshi_api_key_id = None
    settings.kalshi_private_key_path = None
    return KalshiWsManager(settings)


# ---------------------------------------------------------------------------
# _dollars_to_cents
# ---------------------------------------------------------------------------


class TestDollarsToCents:
    def test_typical(self, manager: KalshiWsManager) -> None:
        assert manager._dollars_to_cents("0.4500") == 45

    def test_whole_dollar(self, manager: KalshiWsManager) -> None:
        assert manager._dollars_to_cents("1.0000") == 100

    def test_one_cent(self, manager: KalshiWsManager) -> None:
        assert manager._dollars_to_cents("0.0100") == 1

    def test_none(self, manager: KalshiWsManager) -> None:
        assert manager._dollars_to_cents(None) is None

    def test_garbage(self, manager: KalshiWsManager) -> None:
        assert manager._dollars_to_cents("abc") is None

    def test_rounding(self, manager: KalshiWsManager) -> None:
        assert manager._dollars_to_cents("0.5550") == 56


# ---------------------------------------------------------------------------
# _parse_fp
# ---------------------------------------------------------------------------


class TestParseFp:
    def test_typical(self, manager: KalshiWsManager) -> None:
        assert manager._parse_fp("800.00") == 800.0

    def test_none(self, manager: KalshiWsManager) -> None:
        assert manager._parse_fp(None) is None

    def test_garbage(self, manager: KalshiWsManager) -> None:
        assert manager._parse_fp("xyz") is None


# ---------------------------------------------------------------------------
# _normalize_ticker
# ---------------------------------------------------------------------------


class TestNormalizeTicker:
    def test_full_message(self, manager: KalshiWsManager) -> None:
        raw = {
            "market_ticker": "TEST-TICKER",
            "yes_bid_dollars": "0.4500",
            "yes_ask_dollars": "0.4700",
            "last_price_dollars": "0.4600",
            "volume_fp": "1200.00",
            "open_interest_fp": "500.00",
        }
        result = manager._normalize_ticker(raw)
        assert result == {
            "market_ticker": "TEST-TICKER",
            "yes_bid": 45,
            "yes_ask": 47,
            "last_price": 46,
            "volume": 1200.0,
            "open_interest": 500.0,
        }

    def test_null_prices(self, manager: KalshiWsManager) -> None:
        raw = {
            "market_ticker": "TEST-TICKER",
            "yes_bid_dollars": None,
            "yes_ask_dollars": None,
            "last_price_dollars": None,
        }
        result = manager._normalize_ticker(raw)
        assert result["yes_bid"] is None
        assert result["yes_ask"] is None
        assert result["last_price"] is None

    def test_absent_fields_omitted(self, manager: KalshiWsManager) -> None:
        """Fields not present in the raw message should not appear in output."""
        raw = {"market_ticker": "TEST-TICKER", "yes_bid_dollars": "0.5000"}
        result = manager._normalize_ticker(raw)
        assert result == {"market_ticker": "TEST-TICKER", "yes_bid": 50}
        assert "yes_ask" not in result
        assert "last_price" not in result
        assert "volume" not in result
        assert "open_interest" not in result

    def test_direct_numeric_fields(self, manager: KalshiWsManager) -> None:
        """Direct numeric fields (no _dollars/_fp suffix) are passed through."""
        raw = {
            "market_ticker": "TEST-TICKER",
            "yes_bid": 45,
            "yes_ask": 47,
            "last_price": 46,
            "volume": 1200,
            "open_interest": 500,
        }
        result = manager._normalize_ticker(raw)
        assert result == {
            "market_ticker": "TEST-TICKER",
            "yes_bid": 45,
            "yes_ask": 47,
            "last_price": 46,
            "volume": 1200,
            "open_interest": 500,
        }

    def test_dollar_fields_take_precedence(self, manager: KalshiWsManager) -> None:
        """When both dollar-string and direct fields are present, dollar wins."""
        raw = {
            "market_ticker": "TEST-TICKER",
            "yes_bid_dollars": "0.5000",
            "yes_bid": 99,
        }
        result = manager._normalize_ticker(raw)
        assert result["yes_bid"] == 50

    def test_price_fallback(self, manager: KalshiWsManager) -> None:
        """'price' field is used as last_price fallback."""
        raw = {"market_ticker": "TEST-TICKER", "price": 42}
        result = manager._normalize_ticker(raw)
        assert result["last_price"] == 42

    def test_price_dollars_fallback(self, manager: KalshiWsManager) -> None:
        """'price_dollars' is used as last_price when last_price_dollars absent."""
        raw = {"market_ticker": "TEST-TICKER", "price_dollars": "0.7400"}
        result = manager._normalize_ticker(raw)
        assert result["last_price"] == 74


# ---------------------------------------------------------------------------
# _normalize_orderbook_delta
# ---------------------------------------------------------------------------


class TestNormalizeOrderbookDelta:
    def test_typical(self, manager: KalshiWsManager) -> None:
        raw = {
            "market_ticker": "TEST-TICKER",
            "market_id": "some-uuid",
            "price_dollars": "0.4500",
            "delta_fp": "800.00",
            "side": "yes",
            "ts": "2026-03-31T15:14:57.435534Z",
        }
        result = manager._normalize_orderbook_delta(raw)
        assert result == {
            "market_ticker": "TEST-TICKER",
            "price": 45,
            "delta": 800.0,
            "side": "yes",
        }

    def test_no_side(self, manager: KalshiWsManager) -> None:
        raw = {
            "market_ticker": "TEST-TICKER",
            "price_dollars": "0.5500",
            "delta_fp": "-200.00",
            "side": "no",
        }
        result = manager._normalize_orderbook_delta(raw)
        assert result["side"] == "no"
        assert result["price"] == 55
        assert result["delta"] == -200.0

    def test_raw_fields_stripped(self, manager: KalshiWsManager) -> None:
        """Internal fields like market_id and ts should not appear in output."""
        raw = {
            "market_ticker": "T",
            "market_id": "uuid",
            "price_dollars": "0.10",
            "delta_fp": "1.00",
            "side": "yes",
            "ts": "2026-01-01T00:00:00Z",
        }
        result = manager._normalize_orderbook_delta(raw)
        assert "market_id" not in result
        assert "ts" not in result
        assert "price_dollars" not in result
        assert "delta_fp" not in result


# ---------------------------------------------------------------------------
# _normalize_orderbook_snapshot
# ---------------------------------------------------------------------------


class TestNormalizeOrderbookSnapshot:
    def test_typical(self, manager: KalshiWsManager) -> None:
        raw = {
            "market_ticker": "TEST-TICKER",
            "yes": [["0.4500", "100.00"], ["0.4400", "200.00"]],
            "no": [["0.5500", "150.00"]],
        }
        result = manager._normalize_orderbook_snapshot(raw)
        assert result["market_ticker"] == "TEST-TICKER"
        assert result["yes"] == [[45, 100], [44, 200]]
        assert result["no"] == [[55, 150]]

    def test_empty_book(self, manager: KalshiWsManager) -> None:
        raw = {"market_ticker": "T", "yes": [], "no": []}
        result = manager._normalize_orderbook_snapshot(raw)
        assert result["yes"] == []
        assert result["no"] == []


# ---------------------------------------------------------------------------
# _normalize_trade
# ---------------------------------------------------------------------------


class TestNormalizeTrade:
    def test_typical(self, manager: KalshiWsManager) -> None:
        raw = {
            "trade_id": "11111111-2222-3333-4444-555555555555",
            "market_ticker": "TEST-TICKER",
            "yes_price_dollars": "0.6400",
            "no_price_dollars": "0.3600",
            "count_fp": "25.00",
            "taker_side": "yes",
            "ts": 1743451200,
        }
        result = manager._normalize_trade(raw)
        assert result == {
            "trade_id": "11111111-2222-3333-4444-555555555555",
            "market_ticker": "TEST-TICKER",
            "yes_price": 64,
            "no_price": 36,
            "count": 25.0,
            "taker_side": "yes",
            "ts": 1743451200,
        }

    def test_missing_sides(self, manager: KalshiWsManager) -> None:
        raw = {"market_ticker": "T"}
        result = manager._normalize_orderbook_snapshot(raw)
        assert result["yes"] == []
        assert result["no"] == []


# ---------------------------------------------------------------------------
# _dispatch_message integration
# ---------------------------------------------------------------------------


class TestDispatchNormalization:
    """Verify that _dispatch_message sends normalized payloads to clients."""

    @pytest.mark.asyncio
    async def test_ticker_normalized(self, manager: KalshiWsManager) -> None:
        client_ws = AsyncMock()
        manager._subscriptions["TEST-TICKER"] = {client_ws}

        raw = '{"type":"ticker","sid":1,"seq":10,"msg":{"market_ticker":"TEST-TICKER","yes_bid_dollars":"0.4500","yes_ask_dollars":"0.4700"}}'
        await manager._dispatch_message(raw)

        client_ws.send_json.assert_called_once()
        sent = client_ws.send_json.call_args[0][0]
        assert sent["type"] == "ticker"
        assert sent["msg"]["yes_bid"] == 45
        assert sent["msg"]["yes_ask"] == 47
        assert "yes_bid_dollars" not in sent["msg"]
        assert "yes_ask_dollars" not in sent["msg"]

    @pytest.mark.asyncio
    async def test_orderbook_delta_normalized(self, manager: KalshiWsManager) -> None:
        client_ws = AsyncMock()
        manager._subscriptions["TEST-TICKER"] = {client_ws}

        raw = '{"type":"orderbook_delta","sid":1,"seq":52,"msg":{"market_ticker":"TEST-TICKER","price_dollars":"0.4500","delta_fp":"800.00","side":"yes"}}'
        await manager._dispatch_message(raw)

        client_ws.send_json.assert_called_once()
        sent = client_ws.send_json.call_args[0][0]
        assert sent["type"] == "orderbook_delta"
        assert sent["msg"]["price"] == 45
        assert sent["msg"]["delta"] == 800.0
        assert sent["msg"]["side"] == "yes"
        assert "price_dollars" not in sent["msg"]
        assert "delta_fp" not in sent["msg"]

    @pytest.mark.asyncio
    async def test_system_messages_not_relayed(self, manager: KalshiWsManager) -> None:
        client_ws = AsyncMock()
        manager._subscriptions["TEST-TICKER"] = {client_ws}

        raw = '{"type":"subscribed","msg":{"channel":"ticker"}}'
        await manager._dispatch_message(raw)

        client_ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_trade_normalized(self, manager: KalshiWsManager) -> None:
        client_ws = AsyncMock()
        manager._subscriptions["TEST-TICKER"] = {client_ws}

        raw = '{"type":"trade","sid":1,"seq":99,"msg":{"trade_id":"tid","market_ticker":"TEST-TICKER","yes_price_dollars":"0.4300","no_price_dollars":"0.5700","count_fp":"10.00","taker_side":"no","ts":1743451200}}'
        await manager._dispatch_message(raw)

        client_ws.send_json.assert_called_once()
        sent = client_ws.send_json.call_args[0][0]
        assert sent["type"] == "trade"
        assert sent["msg"]["yes_price"] == 43
        assert sent["msg"]["no_price"] == 57
        assert sent["msg"]["count"] == 10.0
        assert sent["msg"]["taker_side"] == "no"
