from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.catalog.event_card_snapshot import build_event_card_snapshot
from app.services.kalshi.rest_client import KalshiRestClient


@pytest.mark.asyncio
async def test_build_event_card_snapshot_pages_until_cursor_exhausted() -> None:
    client = MagicMock(spec=KalshiRestClient)
    client.get_events = AsyncMock(
        side_effect=[
            {
                "events": [
                    {
                        "event_ticker": "E1",
                        "series_ticker": "KXNBA",
                        "category": "Sports",
                        "title": "Game 1",
                        "sub_title": "Tonight",
                        "mutually_exclusive": False,
                        "last_updated_ts": "2026-03-29T10:00:00Z",
                        "markets": [
                            {
                                "ticker": "M1",
                                "event_ticker": "E1",
                                "market_type": "binary",
                                "yes_sub_title": "Yes",
                                "no_sub_title": "No",
                                "status": "open",
                                "close_time": "2026-03-29T12:00:00Z",
                                "yes_bid_dollars": "0.45",
                                "yes_ask_dollars": "0.47",
                                "last_price_dollars": "0.46",
                                "volume_fp": "10.00",
                                "open_interest_fp": "5.00",
                            }
                        ],
                    }
                ],
                "cursor": "next-1",
            },
            {
                "events": [
                    {
                        "event_ticker": "E2",
                        "series_ticker": "KXBTC",
                        "category": "Crypto",
                        "title": "BTC",
                        "sub_title": None,
                        "mutually_exclusive": True,
                        "last_updated_ts": "2026-03-29T11:00:00Z",
                        "markets": [],
                    }
                ],
                "cursor": "",
            },
        ]
    )

    snapshot = await build_event_card_snapshot(client)

    assert len(snapshot.cards) == 2
    assert snapshot.cards[0].top_markets[0].volume_fp == "10.00"
    assert snapshot.cards[1].total_volume_fp == "0.00"
    assert client.get_events.await_count == 2