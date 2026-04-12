from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch


async def test_create_signal_event_success(async_client):
    payload = {
        "market_ticker": "TEST-MKT",
        "event_ticker": "TEST-EVT",
        "mode": "fast",
        "signal_direction": "BUY",
        "confidence": 72,
        "buy_score": 72,
        "sell_score": 11,
        "entry_note": "Entry test",
        "stop_note": "Stop test",
        "target_note": "Target test",
        "conditions_met": {"strongConfirmations": 3},
        "diagnostics": {"rsi14": 41.2},
        "source": "frontend-market-view",
    }

    with patch("app.routers.signal_events.insert_signal_event", AsyncMock(return_value=1234)):
        response = await async_client.post("/api/signal-events", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["event_id"] == 1234


async def test_list_signal_events_success(async_client):
    now = datetime.now(UTC)
    rows = [
        {
            "id": 7,
            "created_at": now,
            "market_ticker": "TEST-MKT",
            "event_ticker": "TEST-EVT",
            "mode": "fast",
            "signal_direction": "SELL",
            "confidence": 81,
            "buy_score": 12,
            "sell_score": 81,
            "entry_note": "Exit test",
            "stop_note": "—",
            "target_note": "—",
            "conditions_met": {"cliff": True},
            "diagnostics": {"price": 91},
            "source": "frontend-market-view",
        }
    ]

    with patch("app.routers.signal_events.fetch_signal_events", AsyncMock(return_value=rows)):
        response = await async_client.get("/api/signal-events?market_ticker=TEST-MKT&limit=50")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert len(body["events"]) == 1
    event = body["events"][0]
    assert event["id"] == 7
    assert event["market_ticker"] == "TEST-MKT"
    assert event["mode"] == "fast"
    assert event["signal_direction"] == "SELL"
    assert event["sell_score"] == 81


async def test_create_signal_lifecycle_event_success(async_client):
    payload = {
        "market_ticker": "TEST-MKT",
        "event_ticker": "TEST-EVT",
        "mode": "strict",
        "lifecycle_state": "ENTRY_FILLED",
        "signal_direction": "BUY",
        "position_side": "LONG",
        "trigger_price_cents": 48,
        "elapsed_ms": 0,
        "payload": {"reason": "strict_entry"},
        "source": "frontend-market-view",
    }

    with patch("app.routers.signal_events.insert_signal_lifecycle_event", AsyncMock(return_value=4321)):
        response = await async_client.post("/api/signal-events/lifecycle", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["event_id"] == 4321


async def test_list_signal_lifecycle_events_success(async_client):
    now = datetime.now(UTC)
    rows = [
        {
            "id": 9,
            "created_at": now,
            "market_ticker": "TEST-MKT",
            "event_ticker": "TEST-EVT",
            "mode": "strict",
            "lifecycle_state": "EXIT_FILLED",
            "signal_direction": "SELL",
            "position_side": "FLAT",
            "trigger_price_cents": 44,
            "elapsed_ms": 4123,
            "payload": {"pnlCents": -4},
            "source": "frontend-market-view",
        }
    ]

    with patch("app.routers.signal_events.fetch_signal_lifecycle_events", AsyncMock(return_value=rows)):
        response = await async_client.get("/api/signal-events/lifecycle?market_ticker=TEST-MKT&mode=strict&limit=50")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert len(body["events"]) == 1
    event = body["events"][0]
    assert event["id"] == 9
    assert event["mode"] == "strict"
    assert event["lifecycle_state"] == "EXIT_FILLED"
    assert event["position_side"] == "FLAT"


async def test_create_signal_event_open_mode_success(async_client):
    payload = {
        "market_ticker": "TEST-MKT",
        "event_ticker": "TEST-EVT",
        "mode": "open",
        "signal_direction": "BUY",
        "confidence": 61,
        "buy_score": 61,
        "sell_score": 21,
        "entry_note": "Open mode entry",
        "stop_note": "Open mode stop",
        "target_note": "Open mode target",
        "conditions_met": {"mode": "open"},
        "diagnostics": {"profile": "open"},
        "source": "frontend-market-view",
    }

    with patch("app.routers.signal_events.insert_signal_event", AsyncMock(return_value=2222)):
        response = await async_client.post("/api/signal-events", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["event_id"] == 2222
