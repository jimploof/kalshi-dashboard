import { render, screen } from '@testing-library/angular';
import { describe, it, expect } from 'vitest';

import { EventCardListComponent } from './event-card-list.component';
import type { EventCardSummaryDTO } from '../../catalog.service';

const MOCK_CARD: EventCardSummaryDTO = {
  event_ticker: 'KXNBA-2026',
  series_ticker: 'KXNBA',
  category: 'Sports',
  title: 'NBA Champion 2026',
  sub_title: 'Finals matchup',
  mutually_exclusive: true,
  last_updated_ts: null,
  market_count: 2,
  nearest_close_time: null,
  total_volume_fp: '1500.00',
  total_open_interest_fp: '300.00',
  top_markets: [
    {
      ticker: 'KXNBA-2026-BOS',
      event_ticker: 'KXNBA-2026',
      market_type: 'binary',
      yes_sub_title: 'Boston Celtics',
      no_sub_title: null,
      status: 'open',
      close_time: null,
      yes_bid_dollars: '0.45',
      yes_ask_dollars: '0.47',
      last_price_dollars: '0.46',
      volume_fp: '1500.00',
      open_interest_fp: '300.00',
    },
  ],
};

const MOCK_CARD_NO_MARKETS: EventCardSummaryDTO = {
  event_ticker: 'KXBTC-2026',
  series_ticker: 'KXBTC',
  category: 'Crypto',
  title: 'Bitcoin price',
  sub_title: null,
  mutually_exclusive: false,
  last_updated_ts: null,
  market_count: 0,
  nearest_close_time: null,
  total_volume_fp: '0.00',
  total_open_interest_fp: '0.00',
  top_markets: [],
};

describe('EventCardListComponent', () => {
  it('renders loading skeletons when loading=true', async () => {
    const { container } = await render(EventCardListComponent, {
      inputs: { loading: true, cards: [] },
    });
    expect(container.querySelectorAll('.skeleton').length).toBeGreaterThan(0);
  });

  it('shows empty-state when cards is empty and not loading', async () => {
    await render(EventCardListComponent, {
      inputs: { cards: [], loading: false },
    });
    expect(screen.getByText(/No open events/i)).toBeTruthy();
  });

  it('renders a card with its title and series ticker', async () => {
    await render(EventCardListComponent, {
      inputs: { cards: [MOCK_CARD], loading: false },
    });
    expect(screen.getByText('NBA Champion 2026')).toBeTruthy();
    expect(screen.getByText('KXNBA')).toBeTruthy();
  });

  it('shows "2 markets" text for a card with market_count=2', async () => {
    await render(EventCardListComponent, {
      inputs: { cards: [MOCK_CARD], loading: false },
    });
    expect(screen.getByText('2 markets')).toBeTruthy();
  });

  it('shows "0 markets" for a card with no markets', async () => {
    await render(EventCardListComponent, {
      inputs: { cards: [MOCK_CARD_NO_MARKETS], loading: false },
    });
    expect(screen.getByText('0 markets')).toBeTruthy();
  });

  it('formats 1500.00 as "Vol 1.5K"', async () => {
    await render(EventCardListComponent, {
      inputs: { cards: [MOCK_CARD], loading: false },
    });
    expect(screen.getByText('Vol 1.5K')).toBeTruthy();
  });

  it('shows top-market YES bid price', async () => {
    await render(EventCardListComponent, {
      inputs: { cards: [MOCK_CARD], loading: false },
    });
    expect(screen.getByText('0.45')).toBeTruthy();
  });

  it('renders multiple cards', async () => {
    await render(EventCardListComponent, {
      inputs: { cards: [MOCK_CARD, MOCK_CARD_NO_MARKETS], loading: false },
    });
    expect(screen.getByText('NBA Champion 2026')).toBeTruthy();
    expect(screen.getByText('Bitcoin price')).toBeTruthy();
  });
});
