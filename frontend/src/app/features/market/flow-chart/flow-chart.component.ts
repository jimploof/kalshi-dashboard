/**
 * FlowChartComponent — Sports market microstructure / regime analysis chart.
 *
 * Uses live WebSocket trade events as the primary data source:
 *   • Trade ticks aggregated into 10-second OHLCV candles (top 77%)
 *     - Candles are colored by taker-side delta (buy pressure = green, sell = red)
 *     - The live (still-forming) bar is rendered in a muted tint
 *   • Order-book depth ratio (NO depth / total depth) → histogram (bottom 23%)
 *   • Zone reference lines at key price boundaries (8, 18, 35, 65, 82, 92¢)
 *   • ATR-scaled regime detection: CLIFF_FROZEN | DEPTH_WALL | BLOWOUT | CONTESTED_HOT | NORMAL
 *
 * Trade history bootstrap: the `trades` signal already holds up to 300 recent
 * trades when the component mounts, so the chart fills immediately.
 *
 * REST candle history is only used to seed the ATR baseline (avg |Δclose|).
 * Uses TradingView Lightweight Charts v4 API.
 */
import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  effect,
  input,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import {
  ColorType,
  CrosshairMode,
  IChartApi,
  ISeriesApi,
  LineStyle,
  UTCTimestamp,
  createChart,
} from 'lightweight-charts';

import type { CandlestickDTO } from '../market.service';
import type { WsTradeMsg } from '../market-ws.service';

// ── Constants ──────────────────────────────────────────────────────────────

const BAR_SECONDS      = 10;   // tick aggregation window
const MAX_BARS         = 500;  // max closed bars retained
const MAX_DEPTH_SAMPLES = 300; // depth histogram history
const ATR_LIVE_BARS    = 10;   // recent bars for live ATR
const ATR_BASELINE_LEN = 20;   // REST candle bars for ATR baseline
const BASE_BAR_SPACING = 6;

/** Zone boundary prices (YES cents). */
const ZONE_LEVELS = [8, 18, 35, 65, 82, 92] as const;

/** Dark workstation palette — matches other chart components. */
const PALETTE = {
  bg:        '#0d1117',
  grid:      '#1c2128',
  text:      '#c9d1d9',
  border:    '#21262d',
  bull:      '#26a69a',
  bear:      '#ef5350',
  bullLive:  '#26a69a60',
  bearLive:  '#ef535060',
  depthN:    '#607d8b',  // neutral depth bar
  depthY:    '#26a69a',  // YES-heavy (low NO ratio) → green
  depthO:    '#ef5350',  // NO-heavy (high NO ratio) → red
} as const;

const ZONE_COLORS: Record<(typeof ZONE_LEVELS)[number], string> = {
   8: '#ef5350',
  18: '#f59e0b',
  35: '#64748b',
  65: '#64748b',
  82: '#f59e0b',
  92: '#ef5350',
};

const ZONE_TITLES: Record<(typeof ZONE_LEVELS)[number], string> = {
   8: 'NO Cliff',
  18: 'NO Dom',
  35: 'Contested',
  65: 'YES Dom',
  82: 'Blowout',
  92: 'YES Cliff',
};

// ── Local types ────────────────────────────────────────────────────────────

type RegimeLabel = 'CLIFF_FROZEN' | 'DEPTH_WALL' | 'BLOWOUT' | 'CONTESTED_HOT' | 'NORMAL';
type PriceZoneLabel = 'NO_CLIFF' | 'NO_DOMINANT' | 'CONTESTED' | 'YES_DOMINANT' | 'YES_BLOWOUT' | 'YES_CLIFF';

type TickBar = {
  ts: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  buyVol: number;
  sellVol: number;
};

type DepthSample = {
  ts: UTCTimestamp;
  ratio: number;
};

// ── TickAggregator ─────────────────────────────────────────────────────────

/** TypeScript port of the Python TickAggregator pattern. */
class TickAggregator {
  private readonly _barSeconds: number;
  private _closedBars: TickBar[] = [];
  private _barOpenTs: UTCTimestamp | null = null;
  private _open  = 0;
  private _high  = 0;
  private _low   = 0;
  private _close = 0;
  private _volume  = 0;
  private _buyVol  = 0;
  private _sellVol = 0;

  constructor(barSeconds = BAR_SECONDS) {
    this._barSeconds = barSeconds;
  }

  get closedBars(): readonly TickBar[] {
    return this._closedBars;
  }

  get currentBar(): TickBar | null {
    if (this._barOpenTs === null) return null;
    return {
      ts:      this._barOpenTs,
      open:    this._open,
      high:    this._high,
      low:     this._low,
      close:   this._close,
      volume:  this._volume,
      buyVol:  this._buyVol,
      sellVol: this._sellVol,
    };
  }

  /**
   * Ingest one trade tick.
   * Returns a closed TickBar when this tick crossed a bar boundary, else null.
   * `ts` is expected to be a unix integer second (as received from the backend).
   */
  ingest(price: number, size: number, takerSide: 'yes' | 'no', ts: number): TickBar | null {
    const barTs = (Math.floor(ts / this._barSeconds) * this._barSeconds) as UTCTimestamp;
    let closed: TickBar | null = null;

    // If this tick belongs to a new bar, close the current one first.
    if (this._barOpenTs !== null && barTs > this._barOpenTs) {
      closed = {
        ts:      this._barOpenTs,
        open:    this._open,
        high:    this._high,
        low:     this._low,
        close:   this._close,
        volume:  this._volume,
        buyVol:  this._buyVol,
        sellVol: this._sellVol,
      };
      this._closedBars.push(closed);
      if (this._closedBars.length > MAX_BARS) {
        this._closedBars.shift();
      }
      this._resetCurrentBar();
    }

    // Start or extend the current bar.
    if (this._barOpenTs === null) {
      this._barOpenTs = barTs;
      this._open = price;
      this._high = price;
      this._low  = price;
    } else {
      if (price > this._high) this._high = price;
      if (price < this._low)  this._low  = price;
    }

    this._close  = price;
    this._volume += size;
    if (takerSide === 'yes') this._buyVol  += size;
    else                     this._sellVol += size;

    return closed;
  }

  reset(): void {
    this._closedBars = [];
    this._resetCurrentBar();
  }

  private _resetCurrentBar(): void {
    this._barOpenTs = null;
    this._open = this._high = this._low = this._close = 0;
    this._volume = this._buyVol = this._sellVol = 0;
  }
}

// ── Component ──────────────────────────────────────────────────────────────

@Component({
  selector: 'app-flow-chart',
  standalone: true,
  imports: [],
  templateUrl: './flow-chart.component.html',
  styleUrl: './flow-chart.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowChartComponent implements AfterViewInit, OnDestroy {

  // ── Inputs ────────────────────────────────────────────────────────────────
  /** Live trade stream from MarketWsService (newest-first, max 300). */
  readonly trades = input<readonly WsTradeMsg[]>([]);
  /** REST candle history — used only to seed the ATR baseline. */
  readonly candlesticks = input<readonly CandlestickDTO[]>([]);
  /** Live YES-side order book levels (sorted descending by price). */
  readonly yesBids = input<readonly [number, number][]>([]);
  /** Live NO-side order book levels (sorted descending by price). */
  readonly noBids  = input<readonly [number, number][]>([]);
  /** Current YES mid-price in cents (fallback for regime when no bars exist). */
  readonly livePrice = input<number | null>(null);
  /** Ticker pulse — increments on each WS ticker message; drives depth updates. */
  readonly liveTick  = input<number>(0);
  /** Best YES bid in cents. */
  readonly yesBid = input<number | null>(null);
  /** Best YES ask in cents. */
  readonly yesAsk = input<number | null>(null);
  /** Zoom percentage controlling bar spacing (25–400). */
  readonly zoomPercent = input<number>(100);

  // ── DOM reference ─────────────────────────────────────────────────────────
  readonly containerRef = viewChild.required<ElementRef<HTMLDivElement>>('chartContainer');

  // ── Overlay signals (readable from template) ──────────────────────────────
  readonly currentRegime     = signal<RegimeLabel>('NORMAL');
  readonly currentDepthRatio = signal<number | null>(null);
  readonly currentSpread     = signal<number | null>(null);
  readonly currentAtrRatio   = signal<number | null>(null);
  readonly priceZone         = signal<PriceZoneLabel>('CONTESTED');
  readonly closedBarCount    = signal<number>(0);

  // ── Chart state (imperative — LWC is not reactive) ────────────────────────
  private chart: IChartApi | null = null;
  private candleSeries: ISeriesApi<'Candlestick'> | null = null;
  private depthSeries:  ISeriesApi<'Histogram'>   | null = null;
  private resizeObserver: ResizeObserver | null = null;

  // ── Aggregator state (plain fields — not signals) ─────────────────────────
  private _agg = new TickAggregator();
  /** Identity reference of the newest trade we've already ingested. */
  private _knownTop: WsTradeMsg | null = null;
  private _depthHistory: DepthSample[] = [];
  private _baselineATR = 2.0;

  constructor() {
    // ── Effect 1: new trades → ingest into aggregator → update candle series ─
    effect(() => {
      const trades = this.trades();

      // Find trades that arrived since the last effect run.
      const newTrades: WsTradeMsg[] = [];
      if (this._knownTop === null) {
        // First run: consume all available buffered trades.
        newTrades.push(...trades);
      } else {
        for (const t of trades) {
          if (t === this._knownTop) break; // found our previous head → stop
          newTrades.push(t);               // newer than last processed
        }
      }

      // Always advance the watermark, even before the chart is ready.
      if (trades.length > 0) {
        this._knownTop = trades[0]!;
      }

      if (newTrades.length === 0) return;

      // trades[] is newest-first; ingest in chronological order (oldest first).
      const toIngest = newTrades
        .reverse()
        .filter(
          (t): t is WsTradeMsg & { yes_price: number; count: number; taker_side: 'yes' | 'no'; ts: number } =>
            t.yes_price !== null &&
            t.count     !== null &&
            t.taker_side !== null &&
            t.ts        !== null,
        );

      for (const t of toIngest) {
        this._agg.ingest(t.yes_price, t.count, t.taker_side, t.ts);
      }

      // Update chart if it is already initialised; otherwise ngAfterViewInit
      // will call updateCandleChart() once the chart is ready.
      if (this.candleSeries) {
        this.updateCandleChart();
      }
    });

    // ── Effect 2: liveTick → depth histogram + regime overlay ────────────────
    effect(() => {
      void this.liveTick();
      const yesBids = untracked(() => this.yesBids());
      const noBids  = untracked(() => this.noBids());
      const bid     = untracked(() => this.yesBid());
      const ask     = untracked(() => this.yesAsk());
      const live    = untracked(() => this.livePrice());

      if (!this.depthSeries) return;

      // Align depth samples to the same 10-second bar boundary as the candles.
      // This prevents LWC from seeing a new rightmost timestamp every second,
      // which would otherwise cause the chart to auto-scroll between candle updates.
      const nowSec  = Math.floor(Date.now() / 1000);
      const barTs   = (Math.floor(nowSec / BAR_SECONDS) * BAR_SECONDS) as UTCTimestamp;
      const depthRatio = this.computeDepthRatio(yesBids, noBids);

      // Upsert depth sample for the current 10-second bar window.
      const last = this._depthHistory[this._depthHistory.length - 1];
      if (last && last.ts === barTs) {
        this._depthHistory[this._depthHistory.length - 1] = { ts: barTs, ratio: depthRatio };
      } else {
        this._depthHistory.push({ ts: barTs, ratio: depthRatio });
        if (this._depthHistory.length > MAX_DEPTH_SAMPLES) {
          this._depthHistory.shift();
        }
      }

      this.depthSeries.setData(
        this._depthHistory.map(d => ({
          time:  d.ts,
          value: d.ratio * 100,
          color: this.depthColor(d.ratio),
        })),
      );

      // Regime overlay — use live candle close, fall back to ticker price.
      const price = this._agg.currentBar?.close ?? live;
      if (price !== null) {
        const liveATR  = this.computeLiveATR();
        const atrRatio = this._baselineATR > 0 ? liveATR / this._baselineATR : 1;
        const spread   = bid !== null && ask !== null ? ask - bid : null;
        this.currentRegime.set(this.classifyRegime(price, depthRatio, atrRatio, spread));
        this.priceZone.set(this.classifyPriceZone(price));
        this.currentAtrRatio.set(Number(atrRatio.toFixed(2)));
        this.currentSpread.set(spread);
      }
      this.currentDepthRatio.set(depthRatio);
    });

    // ── Effect 3: zoom / bar spacing ─────────────────────────────────────────
    effect(() => {
      const zoom = this.zoomPercent();
      if (this.chart) {
        this.chart.timeScale().applyOptions({
          barSpacing: this.toBarSpacing(zoom),
        });
      }
    });

    // ── Effect 4: seed ATR baseline from REST candle history ──────────────────
    effect(() => {
      const bars = this.candlesticks();
      this._baselineATR = this.computeBaselineATR(bars);
    });
  }

  ngAfterViewInit(): void {
    this.initChart();
    // Render any bars the trade effect already ingested before the chart existed.
    if (this._agg.closedBars.length > 0 || this._agg.currentBar !== null) {
      this.updateCandleChart();
    }
  }

  ngOnDestroy(): void {
    this.resizeObserver?.disconnect();
    this.chart?.remove();
    this.chart = null;
  }

  // ── Chart initialisation ──────────────────────────────────────────────────

  private initChart(): void {
    const container = this.containerRef().nativeElement;

    this.chart = createChart(container, {
      width:  container.clientWidth,
      height: container.clientHeight || 380,
      layout: {
        background: { type: ColorType.Solid, color: PALETTE.bg },
        textColor:  PALETTE.text,
        fontSize:   11,
      },
      grid: {
        vertLines: { color: PALETTE.grid },
        horzLines: { color: PALETTE.grid },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#4a5568', labelBackgroundColor: '#2d3748' },
        horzLine: { color: '#4a5568', labelBackgroundColor: '#2d3748' },
      },
      rightPriceScale: {
        borderColor:  PALETTE.border,
        scaleMargins: { top: 0.03, bottom: 0.25 },
      },
      timeScale: {
        borderColor:    PALETTE.border,
        timeVisible:    true,
        secondsVisible: true,
        rightOffset:    8,
        barSpacing:     this.toBarSpacing(this.zoomPercent()),
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale: {
        mouseWheel: true,
        pinch:      true,
        axisPressedMouseMove: { time: true, price: false },
      },
    });

    // ── Tick-bar candlestick series (locked Y: 0–100) ──────────────────────
    this.candleSeries = this.chart.addCandlestickSeries({
      upColor:          PALETTE.bull,
      downColor:        PALETTE.bear,
      borderUpColor:    PALETTE.bull,
      borderDownColor:  PALETTE.bear,
      wickUpColor:      PALETTE.bull,
      wickDownColor:    PALETTE.bear,
      borderVisible:    true,
      priceLineVisible: false,
      lastValueVisible: true,
      priceFormat:      { type: 'price', precision: 0, minMove: 1 },
      autoscaleInfoProvider: () => ({
        priceRange: { minValue: 0, maxValue: 100 },
        margins:    { above: 0.03, below: 0.25 },
      }),
    });

    // Zone reference lines on the candlestick series.
    for (const level of ZONE_LEVELS) {
      this.candleSeries.createPriceLine({
        price:            level,
        color:            ZONE_COLORS[level],
        lineWidth:        1,
        lineStyle:        LineStyle.Dashed,
        axisLabelVisible: false,
        title:            ZONE_TITLES[level],
      });
    }

    // ── Depth ratio histogram (bottom ~23% of chart area) ─────────────────
    this.depthSeries = this.chart.addHistogramSeries({
      color:            PALETTE.depthN,
      base:             50,
      priceScaleId:     'depth',
      priceLineVisible: false,
      lastValueVisible: false,
      priceFormat:      { type: 'volume' },
    });

    this.chart.priceScale('depth').applyOptions({
      scaleMargins: { top: 0.77, bottom: 0 },
      visible:      false,
    });

    this.depthSeries.createPriceLine({
      price:            50,
      color:            '#4a556840',
      lineWidth:        1,
      lineStyle:        LineStyle.Solid,
      axisLabelVisible: false,
      title:            '',
    });

    requestAnimationFrame(() => {
      if (this.chart && container.clientHeight > 0) {
        this.chart.applyOptions({
          width:  container.clientWidth,
          height: container.clientHeight,
        });
      }
    });

    this.resizeObserver = new ResizeObserver(entries => {
      if (!this.chart) return;
      const entry = entries[0];
      if (!entry) return;
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) {
        this.chart.applyOptions({ width, height });
      }
    });
    this.resizeObserver.observe(container);
  }

  // ── Candle chart update ───────────────────────────────────────────────────

  private updateCandleChart(): void {
    if (!this.candleSeries || !this.chart) return;

    const closed = this._agg.closedBars;
    const live   = this._agg.currentBar;

    type CandlePoint = {
      time: UTCTimestamp;
      open: number; high: number; low: number; close: number;
      color: string; borderColor: string; wickColor: string;
    };

    const points: CandlePoint[] = closed.map(b => ({
      time:        b.ts,
      open:        b.open,
      high:        b.high,
      low:         b.low,
      close:       b.close,
      // Color closed bars by taker-side buy/sell imbalance (CVD direction).
      color:       b.buyVol >= b.sellVol ? PALETTE.bull    : PALETTE.bear,
      borderColor: b.buyVol >= b.sellVol ? PALETTE.bull    : PALETTE.bear,
      wickColor:   b.buyVol >= b.sellVol ? PALETTE.bull    : PALETTE.bear,
    }));

    if (live) {
      points.push({
        time:        live.ts,
        open:        live.open,
        high:        live.high,
        low:         live.low,
        close:       live.close,
        // Live (forming) bar shown in muted tint so it reads as in-progress.
        color:       live.buyVol >= live.sellVol ? PALETTE.bullLive : PALETTE.bearLive,
        borderColor: live.buyVol >= live.sellVol ? PALETTE.bull     : PALETTE.bear,
        wickColor:   live.buyVol >= live.sellVol ? PALETTE.bull     : PALETTE.bear,
      });
    }

    this.candleSeries.setData(points);
    this.closedBarCount.set(closed.length);
    this.chart.timeScale().scrollToPosition(0, false);
  }

  // ── Analytical helpers ────────────────────────────────────────────────────

  /**
   * NO depth / (YES depth + NO depth) using top-5 price levels each side.
   * Returns 0.5 when either side is empty.
   */
  private computeDepthRatio(
    yesBids: readonly [number, number][],
    noBids:  readonly [number, number][],
  ): number {
    const topN   = 5;
    const yesQty = yesBids.slice(0, topN).reduce((acc, [, qty]) => acc + qty, 0);
    const noQty  = noBids.slice(0, topN).reduce((acc, [, qty]) => acc + qty, 0);
    const total  = yesQty + noQty;
    return total === 0 ? 0.5 : noQty / total;
  }

  /**
   * ATR baseline from REST candle history (last N bars avg |Δclose|).
   * Minimum 0.1 to prevent division-by-zero in regime logic.
   */
  private computeBaselineATR(bars: readonly CandlestickDTO[]): number {
    if (bars.length < 2) return 2.0;
    const len   = Math.min(ATR_BASELINE_LEN, bars.length);
    const slice = bars.slice(-len);
    let sum = 0;
    for (let i = 1; i < slice.length; i++) {
      sum += Math.abs(slice[i]!.close - slice[i - 1]!.close);
    }
    return Math.max(sum / (slice.length - 1), 0.1);
  }

  /**
   * Live ATR from recent closed tick bars (last N bars avg |Δclose|).
   * Falls back to the REST baseline when insufficient bars have closed.
   */
  private computeLiveATR(): number {
    const closed = this._agg.closedBars;
    const len    = Math.min(ATR_LIVE_BARS, closed.length);
    if (len < 2) return this._baselineATR;
    const slice = closed.slice(-len);
    let sum = 0;
    for (let i = 1; i < slice.length; i++) {
      sum += Math.abs(slice[i]!.close - slice[i - 1]!.close);
    }
    return sum / (slice.length - 1);
  }

  private classifyPriceZone(price: number): PriceZoneLabel {
    if (price < 8)   return 'NO_CLIFF';
    if (price < 18)  return 'NO_DOMINANT';
    if (price <= 65) return 'CONTESTED';
    if (price <= 82) return 'YES_DOMINANT';
    if (price <= 92) return 'YES_BLOWOUT';
    return 'YES_CLIFF';
  }

  private classifyRegime(
    price:      number,
    depthRatio: number,
    atrRatio:   number,
    spread:     number | null,
  ): RegimeLabel {
    const hasCliffDepth = depthRatio > 0.85 || depthRatio < 0.15;
    const spreadVal     = spread ?? 10;

    if (price < 8 || price > 92) {
      if (hasCliffDepth) return 'DEPTH_WALL';
      if (spreadVal < 3 && atrRatio < 0.6) return 'CLIFF_FROZEN';
      return 'NORMAL';
    }

    if (price < 18 || price > 82) {
      if (hasCliffDepth) return 'DEPTH_WALL';
      if (atrRatio < 0.6) return 'BLOWOUT';
      return 'NORMAL';
    }

    if (price >= 35 && price <= 65) {
      if (atrRatio > 1.5) return 'CONTESTED_HOT';
    }

    return 'NORMAL';
  }

  private depthColor(ratio: number): string {
    if (ratio < 0.35) return PALETTE.depthY;  // YES-heavy → green
    if (ratio > 0.65) return PALETTE.depthO;  // NO-heavy → red
    return PALETTE.depthN;                    // balanced → grey
  }

  // ── Template formatting helpers ───────────────────────────────────────────

  formatDepth(val: number | null): string {
    return val !== null ? `${Math.round(val * 100)}%` : '—';
  }

  formatSpread(val: number | null): string {
    return val !== null ? `${Math.round(val)}¢` : '—';
  }

  formatAtr(val: number | null): string {
    return val !== null ? `${val.toFixed(1)}×` : '—';
  }

  // ── Bar spacing ───────────────────────────────────────────────────────────

  private toBarSpacing(zoomPercent: number): number {
    const normalized = Math.max(25, Math.min(400, zoomPercent));
    return BASE_BAR_SPACING * (normalized / 100);
  }
}
