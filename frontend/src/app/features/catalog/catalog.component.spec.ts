import { render, screen } from '@testing-library/angular';
import { EMPTY, of } from 'rxjs';
import { describe, it, expect } from 'vitest';

import { CatalogComponent } from './catalog.component';
import { CatalogService, type CatalogEventCardsResponse, type CatalogEventDetailResponse } from './catalog.service';

// ── Minimal mock CatalogService ──────────────────────────────────────────────
function makeMockService(
  cardsResponse?: Partial<CatalogEventCardsResponse>,
): Partial<CatalogService> {
  const snap = new Date().toISOString();
  const defaults: CatalogEventCardsResponse = {
    status: 'success',
    cards: [],
    next_cursor: null,
    total: 0,
    snapshot_id: 'test-snap',
    snapshot_built_at: snap,
    stale: false,
    ...cardsResponse,
  };
  return {
    getCategories:  () => EMPTY as ReturnType<CatalogService['getCategories']>,
    getSeries:      () => EMPTY as ReturnType<CatalogService['getSeries']>,
    getEventCards:  () => of(defaults),
    getEventDetail: () => EMPTY as ReturnType<CatalogService['getEventDetail']>,
    getMarketDetail:() => EMPTY as ReturnType<CatalogService['getMarketDetail']>,
    getEvents:      () => EMPTY as ReturnType<CatalogService['getEvents']>,
  };
}

describe('CatalogComponent', () => {
  it('renders welcome message when no category is selected', async () => {
    await render(CatalogComponent, {
      providers: [
        { provide: CatalogService, useValue: makeMockService() },
      ],
    });
    expect(screen.getByText(/Select a category/i)).toBeTruthy();
  });

  it('shows event-cards view after a category is selected', async () => {
    const { fixture } = await render(CatalogComponent, {
      providers: [
        { provide: CatalogService, useValue: makeMockService() },
      ],
    });
    const state = fixture.componentInstance.state;
    state.selectCategory('Sports');
    fixture.detectChanges();
    // In event-cards view the sort toolbar is present
    expect(screen.getByRole('combobox', { name: /Sort events/i })).toBeTruthy();
  });

  it('shows markets view when an event ticker is selected', async () => {
    const { fixture } = await render(CatalogComponent, {
      providers: [
        {
          provide: CatalogService,
          useValue: {
            ...makeMockService(),
            getEventDetail: (): ReturnType<CatalogService['getEventDetail']> => {
              const result: CatalogEventDetailResponse = {
                status: 'success',
                event: {
                  event_ticker: 'E1',
                  markets: [
                    {
                      ticker: 'M1',
                      event_ticker: 'E1',
                      market_type: 'binary',
                      yes_sub_title: 'Yes side',
                      no_sub_title: null,
                      title: null,
                      subtitle: null,
                      status: 'open',
                      open_time: null,
                      close_time: null,
                      yes_bid_dollars: '0.50',
                      yes_ask_dollars: '0.52',
                      last_price_dollars: '0.51',
                      volume_fp: '100.00',
                      volume_24h_fp: '50.00',
                      open_interest_fp: '30.00',
                    },
                  ],
                },
              };
              return of(result);
            },
          },
        },
      ],
    });
    const state = fixture.componentInstance.state;
    state.selectCategory('Sports');
    state.selectEvent('E1');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    // Market list header is present in markets view
    expect(screen.getByText('Ticker')).toBeTruthy();
  });

  it('shows stale badge when snapshot is stale', async () => {
    const { fixture } = await render(CatalogComponent, {
      providers: [
        {
          provide: CatalogService,
          useValue: makeMockService({ stale: true, total: 0 }),
        },
      ],
    });
    const state = fixture.componentInstance.state;
    state.selectCategory('Sports');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getByText(/Refreshing/i)).toBeTruthy();
  });
});
