/**
 * MarketViewComponent — full trading view for a single Kalshi market.
 *
 * Replaces the modal pattern: clicking a market in the catalog navigates to
 * /market/:ticker and this component populates the main content area.
 *
 * Data flow:
 *  1. REST bootstrap: market detail, candlestick history, order book snapshot
 *  2. Live updates: WebSocket via MarketWsService (ticker + orderbook delta)
 *
 * The MarketWsService is provided at the component level so it is scoped to
 * this view and destroyed (+ WS disconnected) when navigation leaves.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { EMPTY, catchError, forkJoin, take } from 'rxjs';

import { MarketService, CandlestickDTO, MarketViewDTO } from '../market.service';
import { MarketWsService } from '../market-ws.service';
import { MarketChartComponent, ChartType } from '../market-chart/market-chart.component';
import { EventChartComponent, OutcomeLine, outcomeColor } from '../event-chart/event-chart.component';

export type ChartMode = 'market' | 'event';

// How many hours of history to load per period option.
const PERIOD_HOURS: Record<number, number> = {
  1:  24,    // 1-min candles → last 24 hours
  5:  72,    // 5-min candles → last 3 days
  15: 168,   // 15-min candles → last 7 days
  60: 720,   // 1-hour candles → last 30 days
};

@Component({
  selector: 'app-market-view',
  standalone: true,
  imports: [MarketChartComponent, EventChartComponent, DecimalPipe],
  providers: [MarketWsService],
  templateUrl: './market-view.component.html',
  styleUrl: './market-view.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MarketViewComponent implements OnInit {
  private readonly route       = inject(ActivatedRoute);
  private readonly router      = inject(Router);
  private readonly marketSvc   = inject(MarketService);
  private readonly destroyRef  = inject(DestroyRef);

  readonly wsService = inject(MarketWsService);

  // ── Route param ───────────────────────────────────────────────────────────
  readonly ticker = signal<string>('');

  // ── Market detail ─────────────────────────────────────────────────────────
  readonly market         = signal<MarketViewDTO | null>(null);
  readonly marketLoading  = signal(true);
  readonly marketError    = signal<string | null>(null);

  // ── Candlestick chart state ───────────────────────────────────────────────
  readonly candlesticks     = signal<readonly CandlestickDTO[]>([]);
  readonly candlesLoading   = signal(false);
  readonly chartType        = signal<ChartType>('auto');
  readonly periodInterval   = signal<number>(1);

  // ── Overlay visibility toggles ────────────────────────────────────────────
  readonly showEma      = signal(true);
  readonly showBid      = signal(true);
  readonly showAsk      = signal(true);
  readonly showSupport  = signal(true);
  readonly showResist   = signal(true);
  readonly showVolume   = signal(true);

  // ── Event chart (multi-outcome) state ─────────────────────────────────────
  readonly chartMode        = signal<ChartMode>('market');
  readonly eventOutcomes    = signal<readonly OutcomeLine[]>([]);
  readonly eventLoading     = signal(false);
  /** Whether the current market's event has >1 outcome (enables Event toggle). */
  readonly hasMultipleOutcomes = signal(false);

  // ── Period selector options ───────────────────────────────────────────────
  readonly periodOptions = [
    { label: '1m',  value: 1  },
    { label: '5m',  value: 5  },
    { label: '15m', value: 15 },
    { label: '1h',  value: 60 },
  ] as const;

  // ── Derived display values ────────────────────────────────────────────────

  /** Live YES bid from WS; falls back to REST snapshot. */
  readonly displayBid = computed(() => {
    const live = this.wsService.yesBid();
    if (live !== null) return live;
    const d = this.market()?.yes_bid_dollars;
    return d ? parseFloat(d) * 100 : null;  // convert dollars → cents
  });

  /** Live YES ask from WS; falls back to REST snapshot. */
  readonly displayAsk = computed(() => {
    const live = this.wsService.yesAsk();
    if (live !== null) return live;
    const d = this.market()?.yes_ask_dollars;
    return d ? parseFloat(d) * 100 : null;
  });

  readonly displayLast = computed(() => {
    const live = this.wsService.lastPrice();
    if (live !== null) return live;
    const d = this.market()?.last_price_dollars;
    return d ? parseFloat(d) * 100 : null;
  });

  readonly statusClass = computed(() => {
    switch (this.market()?.status) {
      case 'open':     return 'badge-status--open';
      case 'closed':   return 'badge-status--closed';
      case 'settled':  return 'badge-status--settled';
      case 'unopened': return 'badge-status--unopened';
      default:         return '';
    }
  });

  readonly marketTitle = computed(() => {
    const m = this.market();
    if (!m) return '';
    return m.title ?? m.yes_sub_title ?? m.ticker;
  });

  // ── Orderbook convenience ─────────────────────────────────────────────────
  readonly yesBids = computed(() => this.wsService.yesBids());
  readonly noBids  = computed(() => this.wsService.noBids());
  readonly spread  = computed(() => this.wsService.spread());
  /** Max quantity on YES side — used to scale depth bars. */
  readonly maxYesQty = computed(() => {
    const bids = this.yesBids();
    return bids.length ? Math.max(...bids.map(b => b[1])) : 1;
  });

  /** Max quantity on NO side — used to scale depth bars. */
  readonly maxNoQty = computed(() => {
    const bids = this.noBids();
    return bids.length ? Math.max(...bids.map(b => b[1])) : 1;
  });

  /** Returns a percentage string for the CSS --depth custom property. */
  depthPct(qty: number, max: number): string {
    return `${Math.round((qty / max) * 100)}%`;
  }
  // ── Lifecycle ─────────────────────────────────────────────────────────────

  ngOnInit(): void {
    this.route.paramMap.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(params => {
      const t = params.get('ticker') ?? '';
      this.ticker.set(t);
      this.loadMarket(t);
    });
  }

  goBack(): void {
    this.router.navigate(['/catalog']);
  }

  setPeriod(minutes: number): void {
    this.periodInterval.set(minutes);
    const m = this.market();
    if (this.chartMode() === 'event') {
      // Re-fetch event chart data with new period.
      if (this.eventOutcomes().length > 0) {
        this.loadEventChart();
      }
    } else if (m?.series_ticker) {
      this.loadCandlesticks(m.ticker, m.series_ticker, minutes);
    }
  }

  setChartType(type: ChartType): void {
    this.chartType.set(type);
  }

  setChartMode(mode: ChartMode): void {
    this.chartMode.set(mode);
    if (mode === 'event' && this.eventOutcomes().length === 0) {
      this.loadEventChart();
    }
  }

  formatCents(cents: number | null): string {
    if (cents === null) return '—';
    return `${cents}¢`;
  }

  formatFp(fp: string | null | undefined): string {
    if (!fp) return '—';
    const n = parseFloat(fp);
    if (isNaN(n)) return '—';
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
    return String(Math.round(n));
  }

  formatDate(iso: string | null | undefined): string {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
    });
  }

  // ── Private helpers ───────────────────────────────────────────────────────

  private loadMarket(ticker: string): void {
    this.marketLoading.set(true);
    this.marketError.set(null);
    this.market.set(null);
    this.candlesticks.set([]);
    this.chartMode.set('market');
    this.eventOutcomes.set([]);
    this.hasMultipleOutcomes.set(false);

    this.marketSvc.getMarket(ticker).pipe(
      take(1),
      catchError(err => {
        this.marketLoading.set(false);
        this.marketError.set('Failed to load market detail.');
        return EMPTY;
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(r => {
      this.marketLoading.set(false);
      if (r.status === 'success' && r.market) {
        this.market.set(r.market);
        // Bootstrap WS subscription.
        this.wsService.connect(ticker);
        // REST orderbook bootstrap — populates the order book immediately
        // while waiting for the first WS orderbook_snapshot message.
        this.marketSvc.getOrderbook(ticker).pipe(
          take(1),
          catchError(() => EMPTY),
          takeUntilDestroyed(this.destroyRef),
        ).subscribe(ob => {
          if (ob.status === 'success') {
            this.wsService.bootstrapOrderbook(
              ob.yes.map(l => [l.price, l.quantity] as [number, number]),
              ob.no.map(l => [l.price, l.quantity] as [number, number]),
            );
          }
        });
        // Load candlestick history.
        if (r.market.series_ticker) {
          this.loadCandlesticks(ticker, r.market.series_ticker, this.periodInterval());
        }
        // Detect multi-outcome events for the Event chart toggle.
        if (r.market.event_ticker) {
          this.marketSvc.getEventOutcomes(r.market.event_ticker).pipe(
            take(1),
            catchError(() => EMPTY),
            takeUntilDestroyed(this.destroyRef),
          ).subscribe(ev => {
            if (ev.status === 'success' && ev.outcomes.length > 1) {
              this.hasMultipleOutcomes.set(true);
            }
          });
        }
      } else if (r.status === 'not_found') {
        this.marketError.set(`Market "${ticker}" not found.`);
      } else {
        this.marketError.set('Could not reach Kalshi API.');
      }
    });
  }

  private loadCandlesticks(ticker: string, seriesTicker: string, periodMinutes: number): void {
    const hoursBack = PERIOD_HOURS[periodMinutes] ?? 24;
    const endTs   = Math.floor(Date.now() / 1000);
    const startTs = endTs - hoursBack * 3600;

    this.candlesLoading.set(true);
    this.marketSvc.getCandlesticks(ticker, {
      seriesTicker,
      startTs,
      endTs,
      periodInterval: periodMinutes,
    }).pipe(
      take(1),
      catchError(() => {
        this.candlesLoading.set(false);
        return EMPTY;
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(r => {
      this.candlesLoading.set(false);
      if (r.status === 'success') {
        this.candlesticks.set(r.candlesticks);
      }
    });
  }

  /** Max outcomes to display on the event chart. */
  private static readonly MAX_OUTCOMES = 4;

  private loadEventChart(): void {
    const m = this.market();
    if (!m?.event_ticker) return;

    this.eventLoading.set(true);

    this.marketSvc.getEventOutcomes(m.event_ticker).pipe(
      take(1),
      catchError(() => {
        this.eventLoading.set(false);
        return EMPTY;
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(ev => {
      if (ev.status !== 'success' || ev.outcomes.length === 0) {
        this.eventLoading.set(false);
        return;
      }

      // Take top N outcomes by price (already sorted desc from backend).
      const topOutcomes = ev.outcomes.slice(
        0, MarketViewComponent.MAX_OUTCOMES,
      );
      const tickers = topOutcomes.map(o => o.ticker);

      const periodMinutes = this.periodInterval();
      const hoursBack = PERIOD_HOURS[periodMinutes] ?? 24;
      const endTs = Math.floor(Date.now() / 1000);
      const startTs = endTs - hoursBack * 3600;

      this.marketSvc.getEventCandlesticks(m.event_ticker!, {
        tickers,
        startTs,
        endTs,
        periodInterval: periodMinutes,
      }).pipe(
        take(1),
        catchError(() => {
          this.eventLoading.set(false);
          return EMPTY;
        }),
        takeUntilDestroyed(this.destroyRef),
      ).subscribe(cr => {
        this.eventLoading.set(false);
        if (cr.status !== 'success') return;

        // Build OutcomeLine array by matching candlestick data to outcomes.
        const candleMap = new Map(
          cr.outcomes.map(o => [o.ticker, o.candlesticks]),
        );
        const lines: OutcomeLine[] = topOutcomes.map((o, i) => ({
          ticker: o.ticker,
          label: o.yes_sub_title ?? o.ticker,
          color: outcomeColor(i),
          candlesticks: candleMap.get(o.ticker) ?? [],
        }));

        this.eventOutcomes.set(lines);
      });
    });
  }
}
