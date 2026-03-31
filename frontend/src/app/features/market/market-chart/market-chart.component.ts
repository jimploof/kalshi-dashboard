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
  untracked,
  viewChild,
} from '@angular/core';
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

export type ChartType = 'candlestick' | 'line' | 'auto';

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
const SR_MERGE    = 2;    // merge pivots within N ticks

@Component({
  selector: 'app-market-chart',
  standalone: true,
  imports: [],
  templateUrl: './market-chart.component.html',
  styleUrl: './market-chart.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MarketChartComponent implements AfterViewInit, OnDestroy {
  // ── Inputs ────────────────────────────────────────────────────────────────
  readonly candlesticks   = input<readonly CandlestickDTO[]>([]);
  readonly yesBid         = input<number | null>(null);
  readonly yesAsk         = input<number | null>(null);
  readonly chartType      = input<ChartType>('candlestick');
  readonly livePrice      = input<number | null>(null);
  readonly periodInterval = input<number>(1);

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
  private resizeObserver: ResizeObserver | null = null;

  constructor() {
    // React to candlestick data changes after chart is initialised.
    effect(() => {
      const data = this.candlesticks();
      if (this.chart) {
        this.updateSeries(data);
      }
    });

    // React to chart type changes — rebuild the price series.
    effect(() => {
      const type = this.chartType();
      if (this.chart) {
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

    // React to live price ticks from WS — update the current bar in real time.
    effect(() => {
      const price = this.livePrice();
      const candles = this.candlesticks();
      if (price === null || !candles.length || !this.chart) return;

      const periodSecs = this.periodInterval() * 60;
      const nowSecs    = Math.floor(Date.now() / 1000);
      const barTs      = (Math.floor(nowSecs / periodSecs) * periodSecs) as UTCTimestamp;
      const last       = candles[candles.length - 1];
      const isSamePeriod =
        barTs === last.ts || (barTs > last.ts && barTs - last.ts < periodSecs);

      if (this.lineSeries) {
        this.lineSeries.update({ time: barTs, value: price });
      }
      if (this.candleSeries) {
        const open     = isSamePeriod ? last.open  : price;
        const prevHigh = isSamePeriod ? last.high  : price;
        const prevLow  = isSamePeriod ? last.low   : price;
        this.candleSeries.update({
          time:  barTs,
          open,
          high:  Math.max(prevHigh, price),
          low:   Math.min(prevLow,  price),
          close: price,
        });
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
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale: { mouseWheel: true, pinch: true },
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
    const resolvedType = initType === 'auto'
      ? this.detectChartType(untracked(() => this.candlesticks()))
      : initType;
    this.applyChartType(resolvedType);

    // Attach bid/ask price lines to the active price series.
    this.createPriceLines();

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

    if (type === 'candlestick') {
      this.candleSeries = this.chart.addCandlestickSeries({
        upColor:         PALETTE.upColor,
        downColor:       PALETTE.dnColor,
        // Borders ensure candle bodies remain visible even at 1-tick scale.
        borderVisible:   true,
        borderUpColor:   PALETTE.upColor,
        borderDownColor: PALETTE.dnColor,
        wickUpColor:     PALETTE.upColor,
        wickDownColor:   PALETTE.dnColor,
        // Suppress the series close-value label so it doesn’t duplicate the Bid
        // price-line label that sits at the same Y coordinate.
        lastValueVisible: false,
        priceFormat:     { type: 'price', precision: 0, minMove: 1 },
      });
    } else {
      this.lineSeries = this.chart.addLineSeries({
        color:            PALETTE.upColor,
        lineWidth:        2,
        lastValueVisible: true,
        priceFormat:      { type: 'price', precision: 0, minMove: 1 },
        title:            'YES Last',
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

    this.bidPriceLine = series.createPriceLine({
      price: this.yesBid() ?? 50,
      color: PALETTE.bidColor,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'Bid',
    });

    this.askPriceLine = series.createPriceLine({
      price: this.yesAsk() ?? 50,
      color: PALETTE.askColor,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'Ask',
    });
  }

  private updateSeries(data: readonly CandlestickDTO[]): void {
    if (!data.length || !this.chart) return;

    // Strip leading all-zero bars that precede any real trading activity.
    const firstActive = data.findIndex(c => c.volume > 0 || c.close > 0);
    const activeData: readonly CandlestickDTO[] = firstActive > 0
      ? data.slice(firstActive)
      : data;

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

    // Always scroll so the most recent bar is visible at the right edge.
    this.chart.timeScale().scrollToRealTime();
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
      title:                  `EMA${EMA_PERIOD}`,
    });
    this.emaSeries.setData(emaData);
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
   * Pivot-based S/R:
   * - Resistance: bar whose high exceeds all highs within ±SR_STRENGTH bars.
   * - Support: bar whose low is below all lows within ±SR_STRENGTH bars.
   * - Nearby levels within SR_MERGE ticks are merged by count.
   * - Returns top 6 levels sorted by how many times each was touched.
   */
  private computeSR(data: readonly CandlestickDTO[]): { level: number; isResistance: boolean }[] {
    type SR = { level: number; isResistance: boolean; count: number };
    const found: SR[] = [];

    for (let i = SR_STRENGTH; i < data.length - SR_STRENGTH; i++) {
      const hi = data[i].high;
      const lo = data[i].low;

      if (hi > 0) {
        let isPivotHigh = true;
        for (let j = i - SR_STRENGTH; j <= i + SR_STRENGTH; j++) {
          if (j !== i && data[j].high >= hi) { isPivotHigh = false; break; }
        }
        if (isPivotHigh) {
          const ex = found.find(l => l.isResistance && Math.abs(l.level - hi) <= SR_MERGE);
          if (ex) ex.count++;
          else found.push({ level: hi, isResistance: true, count: 1 });
        }
      }

      if (lo > 0) {
        let isPivotLow = true;
        for (let j = i - SR_STRENGTH; j <= i + SR_STRENGTH; j++) {
          if (j !== i && data[j].low <= lo) { isPivotLow = false; break; }
        }
        if (isPivotLow) {
          const ex = found.find(l => !l.isResistance && Math.abs(l.level - lo) <= SR_MERGE);
          if (ex) ex.count++;
          else found.push({ level: lo, isResistance: false, count: 1 });
        }
      }
    }

    return found.sort((a, b) => b.count - a.count).slice(0, 6);
  }
}
