/**
 * MarketChartComponent — TradingView Lightweight Charts wrapper.
 *
 * Renders OHLCV candlestick data using the lightweight-charts package
 * (pure local charting — no external API calls, no telemetry).
 *
 * Features:
 *  - Candlestick or Line chart type (controlled via chartType input)
 *  - Volume histogram on a separate price scale
 *  - YES Bid / YES Ask live price lines (updated reactively from WS data)
 *  - ResizeObserver to fill the container width dynamically
 *  - Dark workstation colour scheme
 *
 * Usage:
 *  <app-market-chart
 *    [candlesticks]="candlesticks()"
 *    [yesBid]="wsService.yesBid()"
 *    [yesAsk]="wsService.yesAsk()"
 *    [chartType]="chartType()"
 *  />
 */
import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  effect,
  ElementRef,
  input,
  OnDestroy,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import {
  ChartLegendHelpModalComponent,
  type ChartLegendKey,
} from '../chart-legend-help-modal/chart-legend-help-modal.component';
import {
  ColorType,
  createChart,
  CrosshairMode,
  IChartApi,
  ISeriesApi,
  IPriceLine,
  LineStyle,
  UTCTimestamp,
} from 'lightweight-charts';

import type { CandlestickDTO } from '../market.service';

export type ChartType = 'candlestick' | 'line' | 'auto' | 'obv' | 'flow';

/** Dark workstation palette. */
const PALETTE = {
  bg:        '#0d1117',
  grid:      '#1c2128',
  text:      '#c9d1d9',
  border:    '#21262d',
  upColor:   '#26a69a',
  dnColor:   '#ef5350',
  bidColor:  '#26a69a',
  askColor:  '#ef5350',
  volUp:     '#26a69a55',
  volDn:     '#ef535055',
  emaColor:  '#f0c040',
  srSupport: '#26a69a99',
  srResist:  '#ef535099',
} as const;

const EMA_PERIOD  = 20;   // bars
const SR_STRENGTH = 5;    // pivot lookback each side (bars)
const SR_MIN_MERGE_TICKS = 1; // minimum merge tolerance in ticks
const SR_MAX_LEVELS = 6;
const BASE_BAR_SPACING = 6;

@Component({
  selector: 'app-market-chart',
  standalone: true,
  imports: [ChartLegendHelpModalComponent],
  templateUrl: './market-chart.component.html',
  styleUrl: './market-chart.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MarketChartComponent implements AfterViewInit, OnDestroy {  // ── Legend help modal ──────────────────────────────────────────────────────
  readonly activeLegendHelp = signal<ChartLegendKey | null>(null);
  openLegendHelp(key: ChartLegendKey): void { this.activeLegendHelp.set(key); }
  closeLegendHelp(): void { this.activeLegendHelp.set(null); }
  // ── Inputs ────────────────────────────────────────────────────────────────
  readonly candlesticks   = input<readonly CandlestickDTO[]>([]);
  readonly yesBid         = input<number | null>(null);
  readonly yesAsk         = input<number | null>(null);
  readonly chartType      = input<ChartType>('candlestick');
  readonly livePrice      = input<number | null>(null);
  readonly liveTick       = input<number>(0);
  readonly periodInterval = input<number>(1);
  readonly zoomPercent    = input<number>(100);

  // Overlay visibility toggles (all default true)
  readonly showEma      = input<boolean>(true);
  readonly showBid      = input<boolean>(true);
  readonly showAsk      = input<boolean>(true);
  readonly showSupport  = input<boolean>(true);
  readonly showResist   = input<boolean>(true);
  readonly showVolume   = input<boolean>(true);

  // ── DOM reference ─────────────────────────────────────────────────────────
  readonly containerRef = viewChild.required<ElementRef<HTMLDivElement>>('chartContainer');

  // ── Chart state (not reactive — managed imperatively) ─────────────────────
  private chart: IChartApi | null = null;
  private candleSeries: ISeriesApi<'Candlestick'> | null = null;
  private lineSeries: ISeriesApi<'Line'> | null = null;
  private emaSeries: ISeriesApi<'Line'> | null = null;
  private volumeSeries: ISeriesApi<'Histogram'> | null = null;
  private bidPriceLine: IPriceLine | null = null;
  private askPriceLine: IPriceLine | null = null;
  private srLines: IPriceLine[] = [];
  private yAxisAnchorSeries: ISeriesApi<'Line'> | null = null;
  private resizeObserver: ResizeObserver | null = null;

  /** Tracks the in-progress live bar across multiple ticks within a period. */
  private liveBar: {
    ts: number;
    open: number;
    high: number;
    low: number;
    close: number;
    tickCount: number;
  } | null = null;

  /** Last EMA value so the live bar can extend the indicator incrementally. */
  private lastEmaValue: number | null = null;

  constructor() {
    // React to candlestick data changes after chart is initialised.
    effect(() => {
      const data = this.candlesticks();
      if (this.chart) {
        this.updateSeries(data);
      }
    });

    // React to chart type changes — rebuild the price series.
    // 'obv' and 'flow' are handled by their own components, not this one.
    effect(() => {
      const type = this.chartType();
      if (this.chart && type !== 'obv' && type !== 'flow') {
        const resolved = type === 'auto'
          ? this.detectChartType(untracked(() => this.candlesticks()))
          : type;
        this.applyChartType(resolved);
      }
    });

    // React to live bid/ask updates from WS.
    effect(() => {
      const bid = this.yesBid();
      const visible = this.showBid();
      if (this.bidPriceLine) {
        if (bid !== null && visible) {
          this.bidPriceLine.applyOptions({ price: bid, lineVisible: true, axisLabelVisible: true });
        } else {
          this.bidPriceLine.applyOptions({ lineVisible: visible, axisLabelVisible: visible });
        }
      }
    });

    effect(() => {
      const ask = this.yesAsk();
      const visible = this.showAsk();
      if (this.askPriceLine) {
        if (ask !== null && visible) {
          this.askPriceLine.applyOptions({ price: ask, lineVisible: true, axisLabelVisible: true });
        } else {
          this.askPriceLine.applyOptions({ lineVisible: visible, axisLabelVisible: visible });
        }
      }
    });

    // Toggle EMA visibility.
    effect(() => {
      const visible = this.showEma();
      if (this.emaSeries) {
        this.emaSeries.applyOptions({ visible });
      }
    });

    // Toggle volume visibility.
    effect(() => {
      const visible = this.showVolume();
      if (this.volumeSeries) {
        this.volumeSeries.applyOptions({ visible });
      }
    });

    // Toggle S/R visibility.
    effect(() => {
      const showS = this.showSupport();
      const showR = this.showResist();
      for (const line of this.srLines) {
        const opts = (line as unknown as { options(): { title: string } }).options();
        const isSup = opts.title === 'S';
        const vis = isSup ? showS : showR;
        line.applyOptions({ lineVisible: vis, axisLabelVisible: false });
      }
    });

    // Apply horizontal zoom level from parent toolbar controls.
    effect(() => {
      const zoom = this.zoomPercent();
      if (this.chart) {
        this.chart.timeScale().applyOptions({
          barSpacing: this.toBarSpacing(zoom),
        });
        this.chart.timeScale().scrollToPosition(0, false);
        this.updateYAxisAnchor(untracked(() => this.candlesticks()));
      }
    });

    // React to live price ticks from WS — update the current bar in real time.
    // Tracks running OHLCV state across multiple ticks within each period,
    // and also updates the volume histogram and EMA overlay.
    effect(() => {
      // Trigger this effect on every ticker message, even if the price value
      // itself did not change (signals suppress identical-value sets).
      this.liveTick();

      const price = this.livePrice();
      const candles = this.candlesticks();
      if (price === null || !candles.length || !this.chart) return;

      const periodSecs = this.periodInterval() * 60;
      const nowSecs    = Math.floor(Date.now() / 1000);
      const barTs      = (Math.floor(nowSecs / periodSecs) * periodSecs) as UTCTimestamp;

      // Determine whether we're continuing the current live bar or starting a new one.
      let bar: NonNullable<typeof this.liveBar>;

      if (!this.liveBar || this.liveBar.ts !== barTs) {
        // Starting a new period — reset the running bar state.
        bar = {
          ts: barTs,
          open: price,
          high: price,
          low: price,
          close: price,
          tickCount: 1,
        };
        this.liveBar = bar;
      } else {
        // Same period — update running extrema.
        bar = this.liveBar;
        bar.high  = Math.max(bar.high, price);
        bar.low   = Math.min(bar.low, price);
        bar.close = price;
        bar.tickCount++;
      }

      // Update candlestick series.
      if (this.candleSeries) {
        this.candleSeries.update({
          time:  barTs,
          open:  bar.open,
          high:  bar.high,
          low:   bar.low,
          close: bar.close,
        });
      }

      // Update line series.
      if (this.lineSeries) {
        this.lineSeries.update({ time: barTs, value: price });
      }

      // Update volume histogram for the live bar (tick count as proxy volume).
      if (this.volumeSeries) {
        this.volumeSeries.update({
          time:  barTs,
          value: bar.tickCount,
          color: bar.close >= bar.open ? PALETTE.volUp : PALETTE.volDn,
        });
      }

      // Extend EMA for the live bar.
      if (this.emaSeries && this.lastEmaValue !== null) {
        const k = 2 / (EMA_PERIOD + 1);
        const emaVal = price * k + this.lastEmaValue * (1 - k);
        this.emaSeries.update({ time: barTs, value: emaVal });
      }
    });
  }

  ngAfterViewInit(): void {
    this.initChart();
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
      width: container.clientWidth,
      height: container.clientHeight || 380,
      layout: {
        background: { type: ColorType.Solid, color: PALETTE.bg },
        textColor: PALETTE.text,
        fontSize: 11,
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
        borderColor: PALETTE.border,
        scaleMargins: { top: 0.05, bottom: 0.28 },
      },
      timeScale: {
        borderColor: PALETTE.border,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: this.toBarSpacing(this.zoomPercent()),
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        // Disable price-axis drag so the user cannot accidentally stretch Y.
        axisPressedMouseMove: { time: true, price: false },
      },
    });

    // Volume histogram — separate price scale at the bottom.
    this.volumeSeries = this.chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    this.chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.75, bottom: 0.0 },
      visible: false,   // volume bars are self-explanatory; labels just clutter
    });

    const initType = this.chartType();
    // 'obv' and 'flow' are handled by their own components — default to 'line' if somehow passed here.
    const resolvedType = initType === 'auto' || initType === 'obv' || initType === 'flow'
      ? this.detectChartType(untracked(() => this.candlesticks()))
      : initType;
    this.applyChartType(resolvedType);

    // Populate with initial data (if already loaded) — untracked so reading
    // candlesticks here doesn’t add it as a dep of any outer effect.
    const initialCandles = untracked(() => this.candlesticks());
    if (initialCandles.length) {
      this.updateSeries(initialCandles);
    }

    // Force correct size after the browser has finished its first paint
    // (flex layout may not have correct dimensions at initChart time).
    requestAnimationFrame(() => {
      if (this.chart && container.clientHeight > 0) {
        this.chart.applyOptions({
          width:  container.clientWidth,
          height: container.clientHeight,
        });
      }
    });

    // Resize when the container changes — update BOTH width and height.
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

  // ── Series management ─────────────────────────────────────────────────────

  private applyChartType(type: 'candlestick' | 'line'): void {
    if (!this.chart) return;

    // Clear overlays that hold references to the price series while it still exists.
    this.clearSRLines();
    if (this.emaSeries) {
      this.chart.removeSeries(this.emaSeries);
      this.emaSeries = null;
    }

    // Remove existing price series.
    if (this.candleSeries) {
      this.chart.removeSeries(this.candleSeries);
      this.candleSeries = null;
    }
    if (this.lineSeries) {
      this.chart.removeSeries(this.lineSeries);
      this.lineSeries = null;
    }
    this.bidPriceLine = null;
    this.askPriceLine = null;

    // autoscaleInfoProvider locks the Y axis permanently to the 0-100 cent
    // domain. margins: {above:0, below:0} is critical — a non-zero margin
    // adds that fraction of the 100-unit range as padding (e.g. 0.05 = 5
    // units below 0), which is what causes negative axis values on live charts.
    const autoscaleInfoProvider = () => ({
      priceRange: { minValue: 0, maxValue: 100 },
      margins: { above: 0, below: 0 },
    });

    if (type === 'candlestick') {
      this.candleSeries = this.chart.addCandlestickSeries({
        upColor:         PALETTE.upColor,
        downColor:       PALETTE.dnColor,
        borderVisible:   true,
        borderUpColor:   PALETTE.upColor,
        borderDownColor: PALETTE.dnColor,
        wickUpColor:     PALETTE.upColor,
        wickDownColor:   PALETTE.dnColor,
        lastValueVisible: false,
        priceFormat:     { type: 'price', precision: 0, minMove: 1 },
        autoscaleInfoProvider,
      });
    } else {
      this.lineSeries = this.chart.addLineSeries({
        color:            PALETTE.upColor,
        lineWidth:        2,
        lastValueVisible: true,
        priceFormat:      { type: 'price', precision: 0, minMove: 1 },
        title:            'YES Last',
        autoscaleInfoProvider,
      });

    }

    this.createPriceLines();

    // Re-apply data if already present — use untracked so reading `candlesticks`
    // here does NOT make the `chartType` effect re-run on every data load.
    const currentCandles = untracked(() => this.candlesticks());
    if (currentCandles.length) {
      this.updateSeries(currentCandles);
    }
  }

  private createPriceLines(): void {
    const series = (this.candleSeries ?? this.lineSeries);
    if (!series) return;

    // Defensive cleanup in case this is called again for the same series.
    if (this.bidPriceLine) {
      try { series.removePriceLine(this.bidPriceLine); } catch { /* already gone */ }
      this.bidPriceLine = null;
    }
    if (this.askPriceLine) {
      try { series.removePriceLine(this.askPriceLine); } catch { /* already gone */ }
      this.askPriceLine = null;
    }

    this.bidPriceLine = series.createPriceLine({
      price: this.yesBid() ?? 50,
      color: PALETTE.bidColor,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
    });

    this.askPriceLine = series.createPriceLine({
      price: this.yesAsk() ?? 50,
      color: PALETTE.askColor,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
    });
  }

  private updateSeries(data: readonly CandlestickDTO[]): void {
    if (!data.length || !this.chart) return;

    // Filter out ghost bars where no trades occurred (close=0, volume=0).
    // Kalshi returns candle frames for every period even without activity;
    // plotting null-turned-0 prices causes lines/candles to spike to 0.
    const activeData = data.filter(c => c.close > 0 || c.volume > 0);

    // If chart type is 'auto', resolve from the new data and rebuild if needed.
    const requestedType = this.chartType();
    if (requestedType === 'auto') {
      const resolved = this.detectChartType(activeData);
      const currentIsCandlestick = this.candleSeries !== null;
      const wantCandlestick = resolved === 'candlestick';
      if (currentIsCandlestick !== wantCandlestick) {
        this.applyChartType(resolved);
      }
    }

    // Candlestick data.
    if (this.candleSeries) {
      this.candleSeries.setData(
        activeData.map(c => ({
          time:  c.ts as UTCTimestamp,
          open:  c.open,
          high:  c.high,
          low:   c.low,
          close: c.close,
        })),
      );
    }

    // Line (YES last close price).
    if (this.lineSeries) {
      this.lineSeries.setData(
        activeData.map(c => ({ time: c.ts as UTCTimestamp, value: c.close })),
      );
    }

    // Volume histogram.
    if (this.volumeSeries) {
      this.volumeSeries.setData(
        activeData.map(c => ({
          time:  c.ts as UTCTimestamp,
          value: c.volume,
          color: c.close >= c.open ? PALETTE.volUp : PALETTE.volDn,
        })),
      );
    }

    // EMA overlay.
    this.updateEMA(activeData);

    // Support & resistance levels.
    this.updateSRLevels(activeData);

    // Reset live bar state — fresh candle data means the live bar should
    // start clean on the next WS tick.
    this.liveBar = null;

    this.updateYAxisAnchor(activeData);

    // Scroll to right edge preserving barSpacing (scrollToRealTime resets it).
    this.chart.timeScale().scrollToPosition(0, false);
  }

  // ── EMA overlay ───────────────────────────────────────────────────────────

  private updateEMA(data: readonly CandlestickDTO[]): void {
    if (!this.chart) return;
    if (this.emaSeries) {
      this.chart.removeSeries(this.emaSeries);
      this.emaSeries = null;
    }
    if (data.length < EMA_PERIOD) return;

    const closes  = data.map(c => c.close);
    const emaVals = this.computeEMA(closes, EMA_PERIOD);

    // Only plot from the first valid EMA value (index EMA_PERIOD - 1).
    const emaData = data.slice(EMA_PERIOD - 1).map((c, i) => ({
      time:  c.ts as UTCTimestamp,
      value: emaVals[i + EMA_PERIOD - 1],
    }));

    this.emaSeries = this.chart.addLineSeries({
      // Dashed + semi-transparent so candle bodies remain the dominant visual.
      color:                  PALETTE.emaColor + 'bb',
      lineWidth:              1,
      lineStyle:              LineStyle.Dashed,
      priceLineVisible:       false,
      lastValueVisible:       true,
      crosshairMarkerVisible: false,
      priceFormat:            { type: 'price', precision: 0, minMove: 1 },
    });
    this.emaSeries.setData(emaData);

    // Store the last EMA value so the live price effect can extend it.
    this.lastEmaValue = emaVals[emaVals.length - 1];
  }

  /** Exponential Moving Average — returns array same length as `closes`. */
  private computeEMA(closes: readonly number[], period: number): number[] {
    const k      = 2 / (period + 1);
    const result = new Array<number>(closes.length).fill(0);
    let sum = 0;
    for (let i = 0; i < period; i++) sum += closes[i];
    result[period - 1] = sum / period;
    for (let i = period; i < closes.length; i++) {
      result[i] = closes[i] * k + result[i - 1] * (1 - k);
    }
    return result;
  }

  /**
   * Auto-detect whether candlesticks are meaningful for this dataset.
   * Uses candlesticks when ≥ 3 distinct price levels exist in the active bars;
   * falls back to line when the data is essentially flat.
   */
  private detectChartType(data: readonly CandlestickDTO[]): 'candlestick' | 'line' {
    const prices = new Set<number>();
    for (const c of data) {
      if (c.volume > 0) {
        prices.add(c.open);
        prices.add(c.high);
        prices.add(c.low);
        prices.add(c.close);
      }
      if (prices.size >= 3) return 'candlestick';
    }
    return 'line';
  }

  // ── Support & Resistance ──────────────────────────────────────────────────

  private updateSRLevels(data: readonly CandlestickDTO[]): void {
    this.clearSRLines();
    const series = this.candleSeries ?? this.lineSeries;
    if (!series || data.length < SR_STRENGTH * 2 + 1) return;

    for (const { level, isResistance } of this.computeSR(data)) {
      const line = series.createPriceLine({
        price:            level,
        color:            isResistance ? PALETTE.srResist : PALETTE.srSupport,
        lineWidth:        1,
        lineStyle:        LineStyle.Solid,
        axisLabelVisible: false,
        title:            isResistance ? 'R' : 'S',
      });
      this.srLines.push(line);
    }
  }

  private clearSRLines(): void {
    const series = this.candleSeries ?? this.lineSeries;
    if (series) {
      for (const line of this.srLines) {
        try { series.removePriceLine(line); } catch { /* already gone */ }
      }
    }
    this.srLines = [];
  }

  /**
   * Volatility-aware pivot S/R:
   * - Detects swing pivots on both sides of each bar.
   * - Merges nearby levels using an adaptive tolerance derived from true range.
   * - Scores levels by touch count, swing significance, and recency.
   */
  private computeSR(data: readonly CandlestickDTO[]): { level: number; isResistance: boolean }[] {
    type SR = {
      level: number;
      isResistance: boolean;
      count: number;
      weight: number;
      lastIndex: number;
    };
    const found: SR[] = [];
    const mergeTolerance = this.computeMergeTolerance(data);

    const addOrMerge = (
      level: number,
      isResistance: boolean,
      pivotWeight: number,
      index: number,
    ): void => {
      const existing = found.find(
        l => l.isResistance === isResistance && Math.abs(l.level - level) <= mergeTolerance,
      );

      if (!existing) {
        found.push({
          level,
          isResistance,
          count: 1,
          weight: Math.max(1, pivotWeight),
          lastIndex: index,
        });
        return;
      }

      const nextCount = existing.count + 1;
      existing.level = ((existing.level * existing.count) + level) / nextCount;
      existing.count = nextCount;
      existing.weight += Math.max(1, pivotWeight);
      existing.lastIndex = Math.max(existing.lastIndex, index);
    };

    for (let i = SR_STRENGTH; i < data.length - SR_STRENGTH; i++) {
      const hi = data[i].high;
      const lo = data[i].low;

      if (hi > 0) {
        let isPivotHigh = true;
        for (let j = i - SR_STRENGTH; j <= i + SR_STRENGTH; j++) {
          if (j !== i && data[j].high >= hi) { isPivotHigh = false; break; }
        }
        if (isPivotHigh) {
          const leftLow = Math.min(...data.slice(i - SR_STRENGTH, i).map(c => c.low));
          const rightLow = Math.min(...data.slice(i + 1, i + 1 + SR_STRENGTH).map(c => c.low));
          const swing = hi - Math.max(leftLow, rightLow);
          addOrMerge(hi, true, swing, i);
        }
      }

      if (lo > 0) {
        let isPivotLow = true;
        for (let j = i - SR_STRENGTH; j <= i + SR_STRENGTH; j++) {
          if (j !== i && data[j].low <= lo) { isPivotLow = false; break; }
        }
        if (isPivotLow) {
          const leftHigh = Math.max(...data.slice(i - SR_STRENGTH, i).map(c => c.high));
          const rightHigh = Math.max(...data.slice(i + 1, i + 1 + SR_STRENGTH).map(c => c.high));
          const swing = Math.min(leftHigh, rightHigh) - lo;
          addOrMerge(lo, false, swing, i);
        }
      }
    }

    const latestIndex = Math.max(1, data.length - 1);
    const scored = found.map(level => {
      const recency = level.lastIndex / latestIndex; // 0..1
      const score = (level.count * 2) + level.weight + recency;
      return { ...level, score };
    });

    const strong = scored.filter(level => level.count >= 2);
    const candidates = strong.length > 0 ? strong : scored;

    return candidates
      .sort((a, b) => b.score - a.score)
      .slice(0, SR_MAX_LEVELS)
      .map(({ level, isResistance }) => ({ level, isResistance }));
  }

  /**
   * Adaptive merge tolerance in ticks from recent true-range behavior.
   * This avoids over-clustering in low-vol markets and under-clustering in high-vol markets.
   */
  private computeMergeTolerance(data: readonly CandlestickDTO[]): number {
    if (data.length < 2) return SR_MIN_MERGE_TICKS;

    const trs: number[] = [];
    for (let i = 1; i < data.length; i++) {
      const curr = data[i];
      const prevClose = data[i - 1].close;
      const tr = Math.max(
        curr.high - curr.low,
        Math.abs(curr.high - prevClose),
        Math.abs(curr.low - prevClose),
      );
      if (Number.isFinite(tr) && tr > 0) trs.push(tr);
    }

    if (trs.length === 0) return SR_MIN_MERGE_TICKS;

    const avgTr = trs.reduce((sum, v) => sum + v, 0) / trs.length;
    const tolerance = Math.round(avgTr * 0.25);
    return Math.max(SR_MIN_MERGE_TICKS, tolerance);
  }

  private updateYAxisAnchor(_rawData: readonly CandlestickDTO[]): void {
    // Y-axis range is now locked via autoscaleInfoProvider on the price series.
    // This method is kept as a no-op for call-site compatibility.
    if (this.yAxisAnchorSeries) {
      this.chart?.removeSeries(this.yAxisAnchorSeries);
      this.yAxisAnchorSeries = null;
    }
  }

  private toBarSpacing(zoomPercent: number): number {
    const normalized = Math.max(25, Math.min(400, zoomPercent));
    return BASE_BAR_SPACING * (normalized / 100);
  }
}
