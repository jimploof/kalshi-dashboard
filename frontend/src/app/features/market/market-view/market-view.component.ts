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
  effect,
  inject,
  signal,
} from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { EMPTY, Subscription, catchError, interval, startWith, switchMap, take } from 'rxjs';

import {
  CandlestickDTO,
  MarketService,
  MarketViewDTO,
  QueuePositionsResponse,
  SignalEventRecord,
  SignalLifecycleEventRecord,
} from '../market.service';
import { MarketWsService } from '../market-ws.service';
import { EventWsService } from '../event-ws.service';
import { MarketChartComponent, ChartType } from '../market-chart/market-chart.component';
import { OBVChartComponent } from '../obv-chart/obv-chart.component';
import { FlowChartComponent } from '../flow-chart/flow-chart.component';
import { EventChartComponent, OutcomeLine, outcomeColor } from '../event-chart/event-chart.component';
import { WsDebugModalComponent } from '../ws-debug-modal/ws-debug-modal.component';
import { AnalyticsHelpModalComponent } from '../analytics-help-modal/analytics-help-modal.component';
import { SignalLogModalComponent } from '../signal-log-modal/signal-log-modal.component';
import {
  computeRSI,
  computeEMAValue,
  computeVWAP,
  computeTradeSignal,
  computeTradeSignalLoose,
  computeTradeSignalOpen,
  type TradeSignalResult,
} from '../market-signals.utils';

export type ChartMode = 'market' | 'event';

type QueueTrendPoint = {
  readonly ts: number;
  readonly total: number;
  readonly avg: number;
  readonly count: number;
};

type EventOutcomePrice = {
  readonly ticker: string;
  readonly label: string;
  readonly price: number | null;
};

type LiveCandleState = {
  ts: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type SignalTelemetryPoint = {
  readonly ts: number;
  readonly strictBuyScore: number;
  readonly looseBuyScore: number;
  readonly openBuyScore: number;
  readonly strictDirection: TradeSignalResult['direction'];
  readonly looseDirection: TradeSignalResult['direction'];
  readonly openDirection: TradeSignalResult['direction'];
};

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
  imports: [
    MarketChartComponent,
    OBVChartComponent,
    FlowChartComponent,
    EventChartComponent,
    DecimalPipe,
    WsDebugModalComponent,
    AnalyticsHelpModalComponent,
    SignalLogModalComponent,
  ],
  providers: [MarketWsService, EventWsService],
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
  readonly eventWsService = inject(EventWsService);
  private queuePollSub: Subscription | null = null;

  // ── WS Debug modal ────────────────────────────────────────────────────────
  readonly wsDebugOpen = signal(false);
  openWsDebug(): void { this.wsDebugOpen.set(true); }
  closeWsDebug(): void { this.wsDebugOpen.set(false); }

  // ── Signal log modal ─────────────────────────────────────────────────────
  readonly signalLogOpen = signal(false);
  readonly signalLogLoading = signal(false);
  readonly signalLogError = signal<string | null>(null);
  readonly signalLogModeFilter = signal<'all' | 'strict' | 'fast' | 'open'>('all');
  readonly activeSignalMode = signal<'strict' | 'loose' | 'open'>('strict');
  readonly signalLogEvents = signal<readonly SignalEventRecord[]>([]);
  readonly signalLifecycleEvents = signal<readonly SignalLifecycleEventRecord[]>([]);
  openSignalLog(): void {
    this.signalLogOpen.set(true);
    this.loadSignalEvents();
  }
  closeSignalLog(): void { this.signalLogOpen.set(false); }
  setSignalLogModeFilter(mode: 'all' | 'strict' | 'fast' | 'open'): void {
    if (this.signalLogModeFilter() === mode) return;
    this.signalLogModeFilter.set(mode);
    if (this.signalLogOpen()) {
      this.loadSignalEvents();
    }
  }

  setActiveSignalMode(mode: 'strict' | 'loose' | 'open'): void {
    this.activeSignalMode.set(mode);
  }

  // ── Analytics help modal ─────────────────────────────────────────────────
  readonly activeHelpCard = signal<string | null>(null);
  openHelp(key: string): void { this.activeHelpCard.set(key); }
  closeHelp(): void { this.activeHelpCard.set(null); }

  // ── Panel collapse state ──────────────────────────────────────────────────
  readonly expandedAnalytics = signal(true);
  readonly expandedSignal    = signal(true);

  // ── Route param ───────────────────────────────────────────────────────────
  readonly ticker = signal<string>('');

  // ── Market detail ─────────────────────────────────────────────────────────
  readonly market         = signal<MarketViewDTO | null>(null);
  readonly marketLoading  = signal(true);
  readonly marketError    = signal<string | null>(null);

  // ── Candlestick chart state ───────────────────────────────────────────────
  readonly candlesticks     = signal<readonly CandlestickDTO[]>([]);
  readonly liveSignalCandles = signal<readonly CandlestickDTO[]>([]);
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
  readonly eventOutcomePrices = signal<readonly EventOutcomePrice[]>([]);
  readonly queueSnapshot = signal<QueuePositionsResponse | null>(null);
  readonly queueTrend = signal<readonly QueueTrendPoint[]>([]);
  readonly spreadHistory = signal<readonly number[]>([]);

  private lastLoggedDirection: TradeSignalResult['direction'] | null = null;
  private lastLoggedTicker: string | null = null;
  private lastLoggedFastDirection: TradeSignalResult['direction'] | null = null;
  private lastLoggedOpenDirection: TradeSignalResult['direction'] | null = null;

  // Simulated position lifecycle for whipsaw-safe logging and evaluation.
  readonly paperPositionSide = signal<'FLAT' | 'LONG'>('FLAT');
  readonly paperEntryPrice = signal<number | null>(null);
  readonly paperEntryAtMs = signal<number | null>(null);
  readonly paperEntryMode = signal<'strict' | 'fast' | 'open' | null>(null);
  readonly paperOutcomeFinalized = signal(false);
  readonly paperReentryLockUntilMs = signal<number>(0);
  readonly signalTelemetry = signal<readonly SignalTelemetryPoint[]>([]);
  private readonly minHoldMs = 3000;
  private readonly reentryLockMs = 3000;
  private readonly telemetryWindowSize = 120;
  private lastTelemetryKey: string | null = null;
  private liveCandleState: LiveCandleState | null = null;
  private lastWsCumulativeVolume: number | null = null;
  private liveCandleBaseFingerprint: string | null = null;

  // ── Period selector options ───────────────────────────────────────────────
  readonly periodOptions = [
    { label: '1m',  value: 1  },
    { label: '5m',  value: 5  },
    { label: '15m', value: 15 },
    { label: '1h',  value: 60 },
  ] as const;
  readonly zoomOptions = [25, 50, 75, 100, 150, 200, 300, 400] as const;
  readonly zoomPercent = signal<number>(100);

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

  readonly imbalanceTop5 = computed(() => this.calcImbalance(5));
  readonly imbalanceTop10 = computed(() => this.calcImbalance(10));

  readonly microprice = computed(() => {
    const bid = this.displayBid();
    const ask = this.displayAsk();
    const yesTop = this.yesBids()[0]?.[1] ?? 0;
    const noTop = this.noBids()[0]?.[1] ?? 0;
    if (bid === null || ask === null || yesTop <= 0 || noTop <= 0) {
      return null;
    }
    const weighted = (bid * noTop + ask * yesTop) / (yesTop + noTop);
    return Number(weighted.toFixed(2));
  });

  readonly impliedPressurePct = computed(() => {
    const micro = this.microprice();
    const bid = this.displayBid();
    const ask = this.displayAsk();
    if (micro === null || bid === null || ask === null) return null;
    const mid = (bid + ask) / 2;
    const halfSpread = Math.max((ask - bid) / 2, 0.5);
    const raw = ((micro - mid) / halfSpread) * 100;
    return Math.max(-100, Math.min(100, Number(raw.toFixed(1))));
  });

  readonly spreadStats = computed(() => {
    const values = this.spreadHistory();
    if (!values.length) {
      return { mean: null, min: null, max: null, latest: null, p90: null };
    }
    const sorted = [...values].sort((a, b) => a - b);
    const mean = values.reduce((acc, v) => acc + v, 0) / values.length;
    const p90Index = Math.floor(sorted.length * 0.9);
    return {
      mean: Number(mean.toFixed(2)),
      min: sorted[0],
      max: sorted[sorted.length - 1],
      latest: values[values.length - 1],
      p90: sorted[Math.min(p90Index, sorted.length - 1)],
    };
  });

  readonly depthConcentration = computed(() => {
    const yes = this.yesBids();
    const no = this.noBids();
    return {
      yesTop1Pct: this.concentrationPct(yes, 1),
      yesTop3Pct: this.concentrationPct(yes, 3),
      yesTop5Pct: this.concentrationPct(yes, 5),
      noTop1Pct: this.concentrationPct(no, 1),
      noTop3Pct: this.concentrationPct(no, 3),
      noTop5Pct: this.concentrationPct(no, 5),
    };
  });

  readonly dispersionStats = computed(() => {
    const prices = this.eventOutcomePrices()
      .map(o => o.price)
      .filter((p): p is number => p !== null);
    if (prices.length < 2) {
      return { count: prices.length, stdev: null, range: null, entropy: null };
    }
    const mean = prices.reduce((acc, v) => acc + v, 0) / prices.length;
    const variance = prices.reduce((acc, v) => acc + (v - mean) ** 2, 0) / prices.length;
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const total = prices.reduce((acc, v) => acc + v, 0);
    const entropy = total > 0
      ? -prices
        .map(v => v / total)
        .reduce((acc, p) => acc + (p > 0 ? p * Math.log2(p) : 0), 0)
      : null;
    return {
      count: prices.length,
      stdev: Number(Math.sqrt(variance).toFixed(2)),
      range: Number((max - min).toFixed(2)),
      entropy: entropy === null ? null : Number(entropy.toFixed(3)),
    };
  });

  readonly intradayStats = computed(() => {
    const bars = this.candlesticks();
    if (bars.length < 2) {
      return { returnPct: null, drawdownPct: null, bars: bars.length };
    }
    const first = bars[0]?.open ?? bars[0]?.close;
    const last = bars[bars.length - 1]?.close;
    if (first <= 0) {
      return { returnPct: null, drawdownPct: null, bars: bars.length };
    }
    let peak = bars[0]!.close;
    let maxDd = 0;
    for (const bar of bars) {
      peak = Math.max(peak, bar.close);
      const dd = ((bar.close - peak) / peak) * 100;
      maxDd = Math.min(maxDd, dd);
    }
    return {
      returnPct: Number((((last - first) / first) * 100).toFixed(2)),
      drawdownPct: Number(maxDd.toFixed(2)),
      bars: bars.length,
    };
  });

  readonly candleQuality = computed(() => {
    const bars = this.candlesticks();
    if (!bars.length) {
      return { flatPct: null, largeWickPct: null, gapCount: 0, staleBars: 0 };
    }
    let flat = 0;
    let wickHeavy = 0;
    let gaps = 0;
    for (let i = 0; i < bars.length; i++) {
      const bar = bars[i]!;
      const body = Math.abs(bar.close - bar.open);
      const range = Math.max(1, bar.high - bar.low);
      if (bar.high === bar.low) flat++;
      if ((range - body) / range >= 0.75) wickHeavy++;
      if (i > 0) {
        const prev = bars[i - 1]!;
        if (Math.abs(bar.open - prev.close) >= 4) {
          gaps++;
        }
      }
    }
    return {
      flatPct: Number(((flat / bars.length) * 100).toFixed(1)),
      largeWickPct: Number(((wickHeavy / bars.length) * 100).toFixed(1)),
      gapCount: gaps,
      staleBars: flat,
    };
  });

  readonly recentTrades = computed(() => this.wsService.trades().slice(0, 24));

  readonly aggressorFlow = computed(() => {
    const trades = this.wsService.trades().slice(0, 80);
    if (!trades.length) {
      return { yesVolume: 0, noVolume: 0, net: 0, vwap: null };
    }
    let yesVolume = 0;
    let noVolume = 0;
    let vwapNum = 0;
    let vwapDen = 0;
    for (const trade of trades) {
      const size = trade.count ?? 0;
      const px = trade.yes_price;
      if (trade.taker_side === 'yes') yesVolume += size;
      if (trade.taker_side === 'no') noVolume += size;
      if (px !== null && size > 0) {
        vwapNum += px * size;
        vwapDen += size;
      }
    }
    return {
      yesVolume,
      noVolume,
      net: yesVolume - noVolume,
      vwap: vwapDen > 0 ? Number((vwapNum / vwapDen).toFixed(2)) : null,
    };
  });

  readonly queueTrendStats = computed(() => {
    const snap = this.queueSnapshot();
    const trend = this.queueTrend();
    const first = trend[0]?.total ?? null;
    const last = trend[trend.length - 1]?.total ?? null;
    return {
      orderCount: snap?.order_count ?? 0,
      avg: snap?.avg_queue_position_fp ?? null,
      max: snap?.max_queue_position_fp ?? null,
      total: snap?.total_queue_position_fp ?? null,
      delta: first !== null && last !== null ? Number((last - first).toFixed(0)) : null,
      points: trend.length,
    };
  });

  // ── Predictive analysis ───────────────────────────────────────────────────
  readonly signalCandlesForSignal = computed((): readonly CandlestickDTO[] => {
    const live = this.liveSignalCandles();
    return live.length ? live : this.candlesticks();
  });

  readonly signalCloses = computed(() => this.signalCandlesForSignal().map(c => c.close));

  readonly rsi14 = computed(() =>
    computeRSI(this.signalCloses()),
  );

  readonly ema20ForSignal = computed(() =>
    computeEMAValue(this.signalCloses(), 20),
  );

  readonly vwap = computed(() => computeVWAP(this.signalCandlesForSignal()));

  readonly tradeSignal = computed((): TradeSignalResult => {
    const flow = this.aggressorFlow();
    return computeTradeSignal({
      closes:       this.signalCloses(),
      candles:      this.signalCandlesForSignal(),
      imbalance:    this.imbalanceTop5(),
      pressure:     this.impliedPressurePct(),
      flowNet:      flow.net,
      flowTotal:    flow.yesVolume + flow.noVolume,
      spreadLatest: this.spreadStats().latest,
      spreadP90:    this.spreadStats().p90,
      bid:          this.displayBid(),
      ask:          this.displayAsk(),
      last:         this.displayLast(),
    });
  });

  readonly fastTradeSignal = computed((): TradeSignalResult => {
    const flow = this.aggressorFlow();
    return computeTradeSignalLoose({
      closes:       this.signalCloses(),
      candles:      this.signalCandlesForSignal(),
      imbalance:    this.imbalanceTop5(),
      pressure:     this.impliedPressurePct(),
      flowNet:      flow.net,
      flowTotal:    flow.yesVolume + flow.noVolume,
      spreadLatest: this.spreadStats().latest,
      spreadP90:    this.spreadStats().p90,
      bid:          this.displayBid(),
      ask:          this.displayAsk(),
      last:         this.displayLast(),
    });
  });

  readonly openTradeSignal = computed((): TradeSignalResult => {
    const flow = this.aggressorFlow();
    return computeTradeSignalOpen({
      closes:       this.signalCloses(),
      candles:      this.signalCandlesForSignal(),
      imbalance:    this.imbalanceTop5(),
      pressure:     this.impliedPressurePct(),
      flowNet:      flow.net,
      flowTotal:    flow.yesVolume + flow.noVolume,
      spreadLatest: this.spreadStats().latest,
      spreadP90:    this.spreadStats().p90,
      bid:          this.displayBid(),
      ask:          this.displayAsk(),
      last:         this.displayLast(),
    });
  });

  readonly activeTradeSignal = computed((): TradeSignalResult =>
    this.activeSignalMode() === 'strict'
      ? this.tradeSignal()
      : this.activeSignalMode() === 'loose'
        ? this.fastTradeSignal()
        : this.openTradeSignal(),
  );

  readonly activeSignalApiMode = computed<'strict' | 'fast' | 'open'>(() =>
    this.activeSignalMode() === 'strict'
      ? 'strict'
      : this.activeSignalMode() === 'loose'
        ? 'fast'
        : 'open',
  );

  readonly inactiveTradeSignal = computed((): TradeSignalResult =>
    this.activeSignalMode() === 'strict'
      ? this.fastTradeSignal()
      : this.activeSignalMode() === 'loose'
        ? this.tradeSignal()
        : this.fastTradeSignal(),
  );

  readonly signalTelemetryStats = computed(() => {
    const points = this.signalTelemetry();
    if (!points.length) {
      return {
        windowSize: 0,
        strictAvgBuy: null as number | null,
        looseAvgBuy: null as number | null,
        openAvgBuy: null as number | null,
        avgDelta: null as number | null,
        openDelta: null as number | null,
        strictBuyPct: null as number | null,
        looseBuyPct: null as number | null,
        openBuyPct: null as number | null,
      };
    }

    const total = points.length;
    const strictSum = points.reduce((acc, point) => acc + point.strictBuyScore, 0);
    const looseSum = points.reduce((acc, point) => acc + point.looseBuyScore, 0);
    const openSum = points.reduce((acc, point) => acc + point.openBuyScore, 0);
    const strictBuyTicks = points.filter(point => point.strictDirection === 'BUY').length;
    const looseBuyTicks = points.filter(point => point.looseDirection === 'BUY').length;
    const openBuyTicks = points.filter(point => point.openDirection === 'BUY').length;

    const strictAvg = strictSum / total;
    const looseAvg = looseSum / total;
    const openAvg = openSum / total;

    return {
      windowSize: total,
      strictAvgBuy: Number(strictAvg.toFixed(1)),
      looseAvgBuy: Number(looseAvg.toFixed(1)),
      openAvgBuy: Number(openAvg.toFixed(1)),
      avgDelta: Number((looseAvg - strictAvg).toFixed(1)),
      openDelta: Number((openAvg - strictAvg).toFixed(1)),
      strictBuyPct: Number(((strictBuyTicks / total) * 100).toFixed(1)),
      looseBuyPct: Number(((looseBuyTicks / total) * 100).toFixed(1)),
      openBuyPct: Number(((openBuyTicks / total) * 100).toFixed(1)),
    };
  });

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

  formatSigned(value: number | null, suffix = ''): string {
    if (value === null) return '—';
    const v = Number(value.toFixed(2));
    return `${v > 0 ? '+' : ''}${v}${suffix}`;
  }

  formatPct(value: number | null): string {
    if (value === null) return '—';
    return `${value.toFixed(1)}%`;
  }

  constructor() {
    effect(() => {
      this.wsService.tickerPulse();
      const s = this.spread();
      if (s === null) return;
      this.spreadHistory.update(current => [...current, s].slice(-240));
    });

    effect(() => {
      this.eventWsService.tickerPulse();
      const live = this.eventWsService.livePrices();
      this.eventOutcomePrices.update(current => current.map(outcome => ({
        ...outcome,
        price: live[outcome.ticker] ?? outcome.price,
      })));
    });

    effect(() => {
      this.wsService.tickerPulse();
      this.periodInterval();
      this.rebuildLiveSignalCandles(
        this.candlesticks(),
        this.displayLast(),
        this.wsService.volume(),
      );
    });

    effect(() => {
      const market = this.market();
      if (!market) return;
      const signalResult = this.tradeSignal();
      const fastSignalResult = this.fastTradeSignal();
      const openSignalResult = this.openTradeSignal();

      if (this.lastLoggedTicker !== market.ticker) {
        this.lastLoggedTicker = market.ticker;
        this.lastLoggedDirection = null;
        this.lastLoggedFastDirection = null;
        this.lastLoggedOpenDirection = null;
      }

      // Persist strict-mode transition events.
      if (this.lastLoggedDirection !== signalResult.direction) {
        this.lastLoggedDirection = signalResult.direction;
        this.logSignalTransition(market.ticker, market.event_ticker, 'strict', signalResult);
      }

      // Persist fast-mode transition events for comparison analytics.
      if (this.lastLoggedFastDirection !== fastSignalResult.direction) {
        this.lastLoggedFastDirection = fastSignalResult.direction;
        this.logSignalTransition(market.ticker, market.event_ticker, 'fast', fastSignalResult);
      }

      // Persist open-mode transitions when open mode is active.
      if (this.activeSignalMode() === 'open' && this.lastLoggedOpenDirection !== openSignalResult.direction) {
        this.lastLoggedOpenDirection = openSignalResult.direction;
        this.logSignalTransition(market.ticker, market.event_ticker, 'open', openSignalResult);
      }

      this.recordSignalTelemetry(signalResult, fastSignalResult, openSignalResult);

      // Position-aware lifecycle simulation (paper-mode) with safety valve.
      this.evaluatePaperLifecycle(
        market.ticker,
        market.event_ticker,
        this.activeTradeSignal(),
        this.activeSignalApiMode(),
        signalResult,
        fastSignalResult,
      );
    });

    this.destroyRef.onDestroy(() => {
      this.queuePollSub?.unsubscribe();
      this.queuePollSub = null;
    });
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

  setZoomFromInput(raw: string): void {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return;
    this.setZoom(parsed);
  }

  zoomIn(): void {
    this.setZoom(this.zoomPercent() + 25);
  }

  zoomOut(): void {
    this.setZoom(this.zoomPercent() - 25);
  }

  setChartMode(mode: ChartMode): void {
    this.chartMode.set(mode);
    if (mode === 'event' && this.eventOutcomes().length === 0) {
      this.loadEventChart();
    } else if (mode === 'event') {
      this.eventWsService.connectMany(this.eventOutcomes().map(o => o.ticker));
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
    this.eventWsService.disconnectAll();
    this.queuePollSub?.unsubscribe();
    this.queuePollSub = null;
    this.chartMode.set('market');
    this.eventOutcomes.set([]);
    this.eventOutcomePrices.set([]);
    this.spreadHistory.set([]);
    this.queueSnapshot.set(null);
    this.queueTrend.set([]);
    this.hasMultipleOutcomes.set(false);
    this.lastLoggedTicker = ticker;
    this.lastLoggedDirection = null;
    this.lastLoggedFastDirection = null;
    this.lastLoggedOpenDirection = null;
    this.paperPositionSide.set('FLAT');
    this.paperEntryPrice.set(null);
    this.paperEntryAtMs.set(null);
    this.paperEntryMode.set(null);
    this.paperOutcomeFinalized.set(false);
    this.paperReentryLockUntilMs.set(0);
    this.signalTelemetry.set([]);
    this.lastTelemetryKey = null;
    this.liveSignalCandles.set([]);
    this.liveCandleState = null;
    this.lastWsCumulativeVolume = null;
    this.liveCandleBaseFingerprint = null;

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
        this.startQueuePolling(ticker);
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
            if (ev.status === 'success') {
              const top = ev.outcomes.slice(0, MarketViewComponent.MAX_OUTCOMES);
              this.eventOutcomePrices.set(top.map(o => ({
                ticker: o.ticker,
                label: o.yes_sub_title ?? o.ticker,
                price: o.last_price_dollars ? parseFloat(o.last_price_dollars) * 100 : null,
              })));
              this.eventWsService.connectMany(top.map(o => o.ticker));
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
        this.liveSignalCandles.set(r.candlesticks);
        this.liveCandleState = null;
        this.lastWsCumulativeVolume = this.wsService.volume();
        const lastTs = r.candlesticks[r.candlesticks.length - 1]?.ts ?? 0;
        this.liveCandleBaseFingerprint = `${r.candlesticks.length}:${lastTs}:${this.periodInterval()}`;
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
        if (this.chartMode() === 'event') {
          this.eventWsService.connectMany(lines.map(line => line.ticker));
        }
      });
    });
  }

  private startQueuePolling(ticker: string): void {
    this.queuePollSub?.unsubscribe();
    this.queuePollSub = interval(10000).pipe(
      startWith(0),
      switchMap(() => this.marketSvc.getQueuePositions(ticker).pipe(catchError(() => EMPTY))),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(snapshot => {
      if (snapshot.status !== 'success') return;
      this.queueSnapshot.set(snapshot);
      const total = snapshot.total_queue_position_fp ?? 0;
      const avg = snapshot.avg_queue_position_fp ?? 0;
      const point: QueueTrendPoint = {
        ts: Date.now(),
        total,
        avg,
        count: snapshot.order_count,
      };
      this.queueTrend.update(current => [...current, point].slice(-90));
    });
  }

  private calcImbalance(levels: number): number | null {
    const yesDepth = this.sumDepth(this.yesBids(), levels);
    const noDepth = this.sumDepth(this.noBids(), levels);
    const total = yesDepth + noDepth;
    if (total <= 0) return null;
    return Number((((yesDepth - noDepth) / total) * 100).toFixed(1));
  }

  private concentrationPct(levels: readonly [number, number][], topN: number): number | null {
    const total = this.sumDepth(levels, levels.length);
    if (total <= 0) return null;
    const top = this.sumDepth(levels, topN);
    return Number(((top / total) * 100).toFixed(1));
  }

  private sumDepth(levels: readonly [number, number][], n: number): number {
    return levels.slice(0, n).reduce((acc, [, qty]) => acc + qty, 0);
  }

  private setZoom(next: number): void {
    const clamped = Math.max(25, Math.min(400, Math.round(next / 25) * 25));
    this.zoomPercent.set(clamped);
  }

  private loadSignalEvents(): void {
    const ticker = this.market()?.ticker ?? this.ticker();
    if (!ticker) return;

    this.signalLogLoading.set(true);
    this.signalLogError.set(null);
    const modeFilter = this.signalLogModeFilter();
    const apiMode = modeFilter === 'all' ? undefined : modeFilter;

    this.marketSvc.getSignalEvents({ marketTicker: ticker, mode: apiMode, limit: 400 }).pipe(
      take(1),
      catchError(() => {
        this.signalLogLoading.set(false);
        this.signalLogError.set('Failed to load signal log history.');
        return EMPTY;
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(resp => {
      this.signalLogLoading.set(false);
      if (resp.status !== 'success') {
        this.signalLogError.set('Signal log API returned a failure status.');
        this.signalLogEvents.set([]);
        return;
      }
      this.signalLogEvents.set(resp.events);

      this.marketSvc.getSignalLifecycleEvents({ marketTicker: ticker, mode: apiMode, limit: 600 }).pipe(
        take(1),
        catchError(() => {
          this.signalLogError.set('Failed to load lifecycle history.');
          return EMPTY;
        }),
        takeUntilDestroyed(this.destroyRef),
      ).subscribe(lifecycleResp => {
        if (lifecycleResp.status !== 'success') {
          this.signalLogError.set('Lifecycle history API returned a failure status.');
          this.signalLifecycleEvents.set([]);
          return;
        }
        this.signalLifecycleEvents.set(lifecycleResp.events);
      });
    });
  }

  private buildSignalConditions(signalResult: TradeSignalResult): Record<string, unknown> {
    const fast = this.fastTradeSignal();
    return {
      mode: this.activeSignalApiMode(),
      selectedProfile: this.activeSignalMode(),
      direction: signalResult.direction,
      confidence: signalResult.confidence,
      buyScore: signalResult.buyScore,
      sellScore: signalResult.sellScore,
      tradeable: signalResult.tradeable,
      reasons: signalResult.reasons,
      fastPreview: {
        direction: fast.direction,
        confidence: fast.confidence,
        buyScore: fast.buyScore,
        sellScore: fast.sellScore,
        reasons: fast.reasons,
      },
    };
  }

  private buildSignalDiagnostics(): Record<string, unknown> {
    const flow = this.aggressorFlow();
    const fast = this.fastTradeSignal();
    return {
      capturedAtIso: new Date().toISOString(),
      ticker: this.market()?.ticker ?? this.ticker(),
      eventTicker: this.market()?.event_ticker ?? null,
      periodInterval: this.periodInterval(),
      chartMode: this.chartMode(),
      bid: this.displayBid(),
      ask: this.displayAsk(),
      last: this.displayLast(),
      spread: this.spread(),
      spreadStats: this.spreadStats(),
      imbalanceTop5: this.imbalanceTop5(),
      imbalanceTop10: this.imbalanceTop10(),
      impliedPressurePct: this.impliedPressurePct(),
      flowNet: flow.net,
      flowYesVolume: flow.yesVolume,
      flowNoVolume: flow.noVolume,
      flowVwap: flow.vwap,
      rsi14: this.rsi14(),
      ema20: this.ema20ForSignal(),
      vwap: this.vwap(),
      strictSignal: this.tradeSignal(),
      fastSignal: fast,
      queueTrendStats: this.queueTrendStats(),
      depthConcentration: this.depthConcentration(),
      intradayStats: this.intradayStats(),
      candleQuality: this.candleQuality(),
    };
  }

  private logSignalTransition(
    marketTicker: string,
    eventTicker: string | null,
    mode: 'strict' | 'fast' | 'open',
    signalResult: TradeSignalResult,
  ): void {
    this.marketSvc.createSignalEvent({
      market_ticker: marketTicker,
      event_ticker: eventTicker,
      mode,
      signal_direction: signalResult.direction,
      confidence: signalResult.confidence,
      buy_score: signalResult.buyScore,
      sell_score: signalResult.sellScore,
      entry_note: signalResult.entryNote,
      stop_note: signalResult.stopNote,
      target_note: signalResult.targetNote,
      conditions_met: this.buildSignalConditions(signalResult),
      diagnostics: this.buildSignalDiagnostics(),
      source: 'frontend-market-view',
    }).pipe(
      take(1),
      catchError(() => EMPTY),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(resp => {
      if (resp.status === 'success' && this.signalLogOpen()) {
        this.loadSignalEvents();
      }
    });

    this.logLifecycleEvent({
      marketTicker,
      eventTicker,
      mode,
      lifecycleState: 'SIGNAL_EMITTED',
      signalDirection: signalResult.direction,
      positionSide: this.paperPositionSide(),
      triggerPriceCents: this.displayLast(),
      elapsedMs: null,
      payload: {
        buyScore: signalResult.buyScore,
        sellScore: signalResult.sellScore,
        confidence: signalResult.confidence,
      },
    });
  }

  private evaluatePaperLifecycle(
    marketTicker: string,
    eventTicker: string | null,
    activeSignal: TradeSignalResult,
    activeMode: 'strict' | 'fast' | 'open',
    strictSignal: TradeSignalResult,
    fastSignal: TradeSignalResult,
  ): void {
    const now = Date.now();
    const price = this.displayLast();
    if (price === null) return;

    const side = this.paperPositionSide();
    const entryAt = this.paperEntryAtMs();
    const entryPrice = this.paperEntryPrice();
    const spreadP90 = this.spreadStats().p90 ?? 2;
    const adaptiveAdverseCents = Math.max(2, Math.round(spreadP90 * 1.2));

    if (side === 'FLAT') {
      if (activeSignal.direction !== 'BUY') return;
      if (now < this.paperReentryLockUntilMs()) {
        this.logLifecycleEvent({
          marketTicker,
          eventTicker,
          mode: activeMode,
          lifecycleState: 'ENTRY_ARMED',
          signalDirection: activeSignal.direction,
          positionSide: side,
          triggerPriceCents: price,
          elapsedMs: Math.max(0, this.paperReentryLockUntilMs() - now),
          payload: { blockedByLockout: true },
        });
        return;
      }

      this.paperPositionSide.set('LONG');
      this.paperEntryPrice.set(price);
      this.paperEntryAtMs.set(now);
      this.paperEntryMode.set(activeMode);
      this.paperOutcomeFinalized.set(false);

      this.logLifecycleEvent({
        marketTicker,
        eventTicker,
        mode: activeMode,
        lifecycleState: 'ENTRY_FILLED',
        signalDirection: activeSignal.direction,
        positionSide: 'LONG',
        triggerPriceCents: price,
        elapsedMs: 0,
        payload: {
          minHoldMs: this.minHoldMs,
          lockoutAfterExitMs: this.reentryLockMs,
          strictSignal,
          fastSignal,
        },
      });
      return;
    }

    if (side !== 'LONG' || entryAt === null || entryPrice === null) return;

    const elapsedMs = now - entryAt;
    const adverseMove = entryPrice - price;
    const adverseTriggered = adverseMove >= adaptiveAdverseCents;
    const entryMode = this.paperEntryMode() ?? activeMode;

    if (elapsedMs < this.minHoldMs) {
      this.logLifecycleEvent({
        marketTicker,
        eventTicker,
        mode: entryMode,
        lifecycleState: 'POSITION_MANAGE',
        signalDirection: activeSignal.direction,
        positionSide: 'LONG',
        triggerPriceCents: price,
        elapsedMs,
        payload: {
          holdActive: true,
          adverseMove,
          adaptiveAdverseCents,
        },
      });
      return;
    }

    if (activeSignal.direction === 'SELL' && adverseTriggered) {
      const netOutcome = this.computeNetOutcome(entryPrice, price);

      this.logLifecycleEvent({
        marketTicker,
        eventTicker,
        mode: entryMode,
        lifecycleState: 'EXIT_SIGNALLED',
        signalDirection: 'SELL',
        positionSide: 'LONG',
        triggerPriceCents: price,
        elapsedMs,
        payload: {
          reason: 'time_stop_plus_adverse',
          entryPrice,
          adverseMove,
          adaptiveAdverseCents,
        },
      });

      this.paperPositionSide.set('FLAT');
      this.paperEntryPrice.set(null);
      this.paperEntryAtMs.set(null);
      this.paperReentryLockUntilMs.set(now + this.reentryLockMs);

      this.logLifecycleEvent({
        marketTicker,
        eventTicker,
        mode: entryMode,
        lifecycleState: 'EXIT_FILLED',
        signalDirection: 'SELL',
        positionSide: 'FLAT',
        triggerPriceCents: price,
        elapsedMs,
        payload: {
          reason: 'safety_valve_exit',
          lockoutMs: this.reentryLockMs,
          grossPnlCents: price - entryPrice,
          netPnlCents: netOutcome.netPnlCents,
          costsCents: netOutcome.totalCostsCents,
        },
      });

      this.logLifecycleEvent({
        marketTicker,
        eventTicker,
        mode: entryMode,
        lifecycleState: 'OUTCOME_FINALIZED',
        signalDirection: 'SELL',
        positionSide: 'FLAT',
        triggerPriceCents: price,
        elapsedMs,
        payload: {
          classification: netOutcome.netPnlCents > 0 ? 'good_buy' : 'bad_buy',
          grossPnlCents: price - entryPrice,
          netPnlCents: netOutcome.netPnlCents,
          feeTier: netOutcome.feeTier,
          feeCents: netOutcome.feeCents,
          slippageCents: netOutcome.slippageCents,
          totalCostsCents: netOutcome.totalCostsCents,
        },
      });

      this.paperOutcomeFinalized.set(true);
      this.paperEntryMode.set(null);
    }
  }

  private computeNetOutcome(entryPrice: number, exitPrice: number): {
    feeTier: 'micro' | 'standard' | 'wide';
    feeCents: number;
    slippageCents: number;
    totalCostsCents: number;
    netPnlCents: number;
  } {
    const spreadP90 = this.spreadStats().p90 ?? 2;
    const feeTier: 'micro' | 'standard' | 'wide' =
      spreadP90 <= 2 ? 'micro' : spreadP90 <= 5 ? 'standard' : 'wide';
    const feeCents = feeTier === 'micro' ? 1 : feeTier === 'standard' ? 2 : 3;
    const slippageCents = Math.max(1, Math.round(spreadP90 * 0.35));
    const totalCostsCents = feeCents + slippageCents;

    return {
      feeTier,
      feeCents,
      slippageCents,
      totalCostsCents,
      netPnlCents: exitPrice - entryPrice - totalCostsCents,
    };
  }

  private rebuildLiveSignalCandles(
    baseCandles: readonly CandlestickDTO[],
    livePrice: number | null,
    wsCumulativeVolume: number | null,
  ): void {
    if (!baseCandles.length) {
      this.liveSignalCandles.set([]);
      this.liveCandleState = null;
      this.lastWsCumulativeVolume = wsCumulativeVolume;
      this.liveCandleBaseFingerprint = null;
      return;
    }

    const periodSecs = this.periodInterval() * 60;
    const bucketTs = Math.floor(Date.now() / periodSecs) * periodSecs;
    const lastBase = baseCandles[baseCandles.length - 1]!;
    const fingerprint = `${baseCandles.length}:${lastBase.ts}:${this.periodInterval()}`;

    if (fingerprint !== this.liveCandleBaseFingerprint) {
      this.liveCandleBaseFingerprint = fingerprint;
      this.liveCandleState = null;
      this.liveSignalCandles.set(baseCandles);
      this.lastWsCumulativeVolume = wsCumulativeVolume;
    }

    if (livePrice === null) {
      this.liveSignalCandles.set(baseCandles);
      this.lastWsCumulativeVolume = wsCumulativeVolume;
      return;
    }

    const baseHasCurrentBucket = lastBase.ts === bucketTs;

    if (!this.liveCandleState || this.liveCandleState.ts !== bucketTs) {
      const seedOpen = baseHasCurrentBucket ? lastBase.open : lastBase.close;
      const seedHigh = baseHasCurrentBucket ? Math.max(lastBase.high, livePrice) : livePrice;
      const seedLow = baseHasCurrentBucket ? Math.min(lastBase.low, livePrice) : livePrice;
      const seedVolume = baseHasCurrentBucket ? lastBase.volume : 0;

      this.liveCandleState = {
        ts: bucketTs,
        open: seedOpen,
        high: seedHigh,
        low: seedLow,
        close: livePrice,
        volume: seedVolume,
      };
    } else {
      this.liveCandleState.high = Math.max(this.liveCandleState.high, livePrice);
      this.liveCandleState.low = Math.min(this.liveCandleState.low, livePrice);
      this.liveCandleState.close = livePrice;
    }

    if (wsCumulativeVolume !== null) {
      const prev = this.lastWsCumulativeVolume;
      if (prev !== null) {
        const delta = wsCumulativeVolume - prev;
        if (delta > 0 && delta < 1_000_000) {
          this.liveCandleState.volume += delta;
        }
      }
      this.lastWsCumulativeVolume = wsCumulativeVolume;
    }

    const liveBar: CandlestickDTO = {
      ts: this.liveCandleState.ts,
      open: this.liveCandleState.open,
      high: this.liveCandleState.high,
      low: this.liveCandleState.low,
      close: this.liveCandleState.close,
      volume: Math.max(0, Math.round(this.liveCandleState.volume)),
    };

    const next = [...baseCandles];
    if (next[next.length - 1]?.ts === liveBar.ts) {
      next[next.length - 1] = liveBar;
    } else {
      next.push(liveBar);
    }
    this.liveSignalCandles.set(next);
  }

  private recordSignalTelemetry(
    strictSignal: TradeSignalResult,
    looseSignal: TradeSignalResult,
    openSignal: TradeSignalResult,
  ): void {
    const price = this.displayLast();
    const key = `${strictSignal.buyScore}|${strictSignal.direction}|${looseSignal.buyScore}|${looseSignal.direction}|${openSignal.buyScore}|${openSignal.direction}|${price ?? 'na'}`;
    if (key === this.lastTelemetryKey) return;
    this.lastTelemetryKey = key;

    const point: SignalTelemetryPoint = {
      ts: Date.now(),
      strictBuyScore: strictSignal.buyScore,
      looseBuyScore: looseSignal.buyScore,
      openBuyScore: openSignal.buyScore,
      strictDirection: strictSignal.direction,
      looseDirection: looseSignal.direction,
      openDirection: openSignal.direction,
    };
    this.signalTelemetry.update(current => [...current, point].slice(-this.telemetryWindowSize));
  }

  private logLifecycleEvent(args: {
    marketTicker: string;
    eventTicker: string | null;
    mode: 'strict' | 'fast' | 'open';
    lifecycleState: SignalLifecycleEventRecord['lifecycle_state'];
    signalDirection: 'BUY' | 'SELL' | 'WAIT' | null;
    positionSide: 'FLAT' | 'LONG';
    triggerPriceCents: number | null;
    elapsedMs: number | null;
    payload: Record<string, unknown>;
  }): void {
    this.marketSvc.createSignalLifecycleEvent({
      market_ticker: args.marketTicker,
      event_ticker: args.eventTicker,
      mode: args.mode,
      lifecycle_state: args.lifecycleState,
      signal_direction: args.signalDirection,
      position_side: args.positionSide,
      trigger_price_cents: args.triggerPriceCents,
      elapsed_ms: args.elapsedMs,
      payload: args.payload,
      source: 'frontend-market-view',
    }).pipe(
      take(1),
      catchError(() => EMPTY),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe();
  }
}
