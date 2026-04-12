/**
 * OBVChartComponent — On-Balance Volume with dual Kalman-filtered ribbon.
 *
 * Implements the TechnicalZen "OBV Kalman Improv" indicator logic:
 *   1. Compute OBV accumulation from CandlestickDTO close + volume
 *   2. Normalize OBV to 0-100 via rolling min-max (lookback = DETREND_LEN)
 *   3. Render as stair-step candlesticks with position-based gradient coloring
 *   4. Overlay two Kalman-filtered lines (short + long) as a directional ribbon
 *   5. Reference lines at 30, 50, 70
 *
 * Uses TradingView Lightweight Charts v4 API.
 * Operates on historical REST candlesticks only — no live bar extension.
 */
import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  effect,
  input,
  viewChild,
} from '@angular/core';
import {
  ColorType,
  CrosshairMode,
  IChartApi,
  ISeriesApi,
  IPriceLine,
  LineStyle,
  UTCTimestamp,
  createChart,
} from 'lightweight-charts';

import type { CandlestickDTO } from '../market.service';

// ── Constants ──────────────────────────────────────────────────────────────

const DETREND_LEN    = 50;   // rolling min-max lookback
const KF_SHORT_LEN   = 20;   // short Kalman filter length
const KF_LONG_LEN    = 80;   // long Kalman filter length
const KF_R           = 0.01; // measurement noise
const KF_Q           = 0.10; // process noise
const BASE_BAR_SPACING = 6;

/** Dark workstation palette — matches market-chart.component.ts. */
const PALETTE = {
  bg:      '#0d1117',
  grid:    '#1c2128',
  text:    '#c9d1d9',
  border:  '#21262d',
  bull:    '#26a69a',
  bear:    '#ef5350',
  ref:     '#4a556880',  // muted for 30/50/70 reference lines
  refFull: '#4a5568',
} as const;

// Gradient stops matching TechnicalZen positions
const GRAD_GREEN  = '#00e640';
const GRAD_YELLOW = '#e6e600';
const GRAD_RED    = '#e61e1e';

@Component({
  selector: 'app-obv-chart',
  standalone: true,
  imports: [],
  templateUrl: './obv-chart.component.html',
  styleUrl: './obv-chart.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OBVChartComponent implements AfterViewInit, OnDestroy {

  // ── Inputs ────────────────────────────────────────────────────────────────
  readonly candlesticks   = input<readonly CandlestickDTO[]>([]);
  readonly periodInterval = input<number>(1);
  readonly zoomPercent    = input<number>(100);

  // ── DOM reference ─────────────────────────────────────────────────────────
  readonly containerRef = viewChild.required<ElementRef<HTMLDivElement>>('chartContainer');

  // ── Chart state (imperative — LWC is not reactive) ────────────────────────
  private chart: IChartApi | null = null;
  private obvSeries:   ISeriesApi<'Candlestick'> | null = null;
  private kfShortSeries: ISeriesApi<'Line'> | null = null;
  private kfLongSeries:  ISeriesApi<'Line'> | null = null;
  private refLines: IPriceLine[] = [];
  private resizeObserver: ResizeObserver | null = null;

  constructor() {
    // Re-render whenever candlestick data changes.
    effect(() => {
      const data = this.candlesticks();
      if (this.chart) {
        this.updateOBVChart(data);
      }
    });

    // Apply bar spacing from zoom control.
    effect(() => {
      const zoom = this.zoomPercent();
      if (this.chart) {
        this.chart.timeScale().applyOptions({
          barSpacing: this.toBarSpacing(zoom),
        });
        this.chart.timeScale().scrollToPosition(0, false);
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

  // ── Initialisation ────────────────────────────────────────────────────────

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
        borderColor: PALETTE.border,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      timeScale: {
        borderColor:   PALETTE.border,
        timeVisible:   true,
        secondsVisible: false,
        rightOffset:   8,
        barSpacing:    this.toBarSpacing(this.zoomPercent()),
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale: {
        mouseWheel: true,
        pinch:      true,
        axisPressedMouseMove: { time: true, price: false },
      },
    });

    // OBV stair-step candlestick series, Y-axis locked 0-100.
    const autoscaleInfoProvider = (): { priceRange: { minValue: number; maxValue: number }; margins: { above: number; below: number } } => ({
      priceRange: { minValue: 0, maxValue: 100 },
      margins:    { above: 0, below: 0 },
    });

    this.obvSeries = this.chart.addCandlestickSeries({
      upColor:          PALETTE.bull,
      downColor:        PALETTE.bear,
      borderVisible:    true,
      borderUpColor:    PALETTE.bull,
      borderDownColor:  PALETTE.bear,
      wickUpColor:      PALETTE.bull,
      wickDownColor:    PALETTE.bear,
      lastValueVisible: false,
      priceFormat:      { type: 'price', precision: 1, minMove: 0.1 },
      autoscaleInfoProvider,
    });

    // Reference lines at 70 / 50 / 30 on the OBV series.
    for (const level of [70, 50, 30]) {
      const line = this.obvSeries.createPriceLine({
        price:            level,
        color:            PALETTE.refFull,
        lineWidth:        1,
        lineStyle:        LineStyle.Dashed,
        axisLabelVisible: true,
        title:            '',
      });
      this.refLines.push(line);
    }

    // Short KF line.
    this.kfShortSeries = this.chart.addLineSeries({
      color:                  PALETTE.bull,
      lineWidth:              1,
      priceLineVisible:       false,
      lastValueVisible:       false,
      crosshairMarkerVisible: false,
      priceFormat:            { type: 'price', precision: 1, minMove: 0.1 },
    });

    // Long KF line.
    this.kfLongSeries = this.chart.addLineSeries({
      color:                  PALETTE.bear,
      lineWidth:              2,
      priceLineVisible:       false,
      lastValueVisible:       false,
      crosshairMarkerVisible: false,
      priceFormat:            { type: 'price', precision: 1, minMove: 0.1 },
    });

    // Populate with initial data if already loaded.
    const initial = this.candlesticks();
    if (initial.length) {
      this.updateOBVChart(initial);
    }

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

  // ── OBV chart update ──────────────────────────────────────────────────────

  private updateOBVChart(data: readonly CandlestickDTO[]): void {
    if (!this.chart || !this.obvSeries || !this.kfShortSeries || !this.kfLongSeries) return;

    // Filter ghost bars — same guard as market-chart.component.ts.
    const active = data.filter(c => c.close > 0 || c.volume > 0);
    if (active.length < 2) {
      this.obvSeries.setData([]);
      this.kfShortSeries.setData([]);
      this.kfLongSeries.setData([]);
      return;
    }

    // Stage 1 — Compute raw OBV accumulation.
    const obvRaw = this.computeOBV(active);

    // Stage 2 — Normalize OBV to 0-100.
    const obvNorm = this.normalizeOBV(obvRaw, DETREND_LEN);

    // Stage 3 — Kalman filter both lengths on the raw OBV, then normalize.
    const kfShortRaw = this.kalmanFilter(obvRaw, KF_SHORT_LEN, KF_R, KF_Q);
    const kfLongRaw  = this.kalmanFilter(obvRaw, KF_LONG_LEN,  KF_R, KF_Q);
    const kfShortNorm = this.normalizeOBV(kfShortRaw, DETREND_LEN);
    const kfLongNorm  = this.normalizeOBV(kfLongRaw,  DETREND_LEN);

    // Stage 4 — Build stair-step candle data with per-bar gradient colors.
    const candleData = this.buildStairStepCandles(active, obvNorm, kfShortNorm, kfLongNorm);

    this.obvSeries.setData(candleData);

    // KF lines — color short KF by slope direction; long KF by crossover state.
    this.kfShortSeries.setData(
      active.map((c, i) => ({
        time:  c.ts as UTCTimestamp,
        value: kfShortNorm[i],
        color: i === 0
          ? PALETTE.bull
          : kfShortNorm[i] >= kfShortNorm[i - 1] ? PALETTE.bull : PALETTE.bear,
      })),
    );

    this.kfLongSeries.setData(
      active.map((c, i) => ({
        time:  c.ts as UTCTimestamp,
        value: kfLongNorm[i],
        color: kfShortNorm[i] >= kfLongNorm[i] ? PALETTE.bull : PALETTE.bear,
      })),
    );

    this.chart.timeScale().scrollToPosition(0, false);
  }

  // ── OBV computation ───────────────────────────────────────────────────────

  /**
   * Compute raw OBV accumulation.
   * barDelta = +volume on up-close bar, -volume on down-close bar, 0 on doji.
   */
  private computeOBV(data: readonly CandlestickDTO[]): number[] {
    const result = new Array<number>(data.length).fill(0);
    let running = 0;
    for (let i = 0; i < data.length; i++) {
      if (i === 0) {
        result[0] = 0;
        continue;
      }
      const delta = data[i].close > data[i - 1].close
        ?  data[i].volume
        : data[i].close < data[i - 1].close
        ? -data[i].volume
        : 0;
      running += delta;
      result[i] = running;
    }
    return result;
  }

  /**
   * Normalize an array to 0-100 using a rolling min-max window.
   * Span guard prevents division by zero on flat markets.
   */
  private normalizeOBV(src: readonly number[], lookback: number): number[] {
    const n = src.length;
    const result = new Array<number>(n).fill(50);
    for (let i = 0; i < n; i++) {
      const start = Math.max(0, i - lookback + 1);
      let lo = src[start];
      let hi = src[start];
      for (let j = start + 1; j <= i; j++) {
        if (src[j] < lo) lo = src[j];
        if (src[j] > hi) hi = src[j];
      }
      const span = Math.max(hi - lo, 1e-10);
      result[i] = ((src[i] - lo) / span) * 100;
    }
    return result;
  }

  /**
   * Kalman filter — matches TechnicalZen Pine Script logic exactly.
   *   meas = R * length
   *   gain = err / (err + meas)
   *   est  = est + gain * (src - est)
   *   err  = (1 - gain) * err + Q / length
   */
  private kalmanFilter(src: readonly number[], length: number, R: number, Q: number): number[] {
    const n = src.length;
    const result = new Array<number>(n).fill(0);
    let est = src[0];
    let err = 1.0;
    const meas = R * length;
    for (let i = 0; i < n; i++) {
      const gain = err / (err + meas);
      est = est + gain * (src[i] - est);
      err = (1.0 - gain) * err + Q / length;
      result[i] = est;
    }
    return result;
  }

  /**
   * Build stair-step candlestick data with per-bar gradient coloring.
   * open[i] = close[i-1] (stair-step, no gaps).
   * Color is determined by the midpoint position in the 0-100 range.
   */
  private buildStairStepCandles(
    data: readonly CandlestickDTO[],
    normArr: readonly number[],
    kfShortNorm: readonly number[],
    kfLongNorm: readonly number[],
  ): Array<{
    time:        UTCTimestamp;
    open:        number;
    high:        number;
    low:         number;
    close:       number;
    color:       string;
    borderColor: string;
    wickColor:   string;
  }> {
    const result = [];
    for (let i = 0; i < data.length; i++) {
      const closeVal = normArr[i];
      const openVal  = i === 0 ? closeVal : normArr[i - 1];
      const high     = Math.max(openVal, closeVal);
      const low      = Math.min(openVal, closeVal);
      const midBody  = (openVal + closeVal) / 2;
      const c        = this.gradientColor(midBody);
      // Determine wicks based on KF context — bull/bear wick tint
      const isBull   = kfShortNorm[i] >= kfLongNorm[i];
      const wickCol  = isBull ? PALETTE.bull + '99' : PALETTE.bear + '99';
      result.push({
        time:        data[i].ts as UTCTimestamp,
        open:        openVal,
        high,
        low,
        close:       closeVal,
        color:       c,
        borderColor: c,
        wickColor:   wickCol,
      });
    }
    return result;
  }

  /**
   * Position-based gradient color matching TechnicalZen gradient:
   *   ≥ 70  → bright green
   *   50-70 → green → yellow
   *   30-50 → yellow → orange-red
   *   ≤ 30  → deep red
   */
  private gradientColor(midBody: number): string {
    const v = Math.max(0, Math.min(100, midBody));
    if (v >= 70) {
      // 70-100: yellow → green
      return this.lerpHex(GRAD_YELLOW, GRAD_GREEN, (v - 70) / 30);
    } else if (v >= 50) {
      // 50-70: deep red → yellow (neutral)
      return this.lerpHex(GRAD_YELLOW, GRAD_GREEN, (v - 50) / 20 * 0.4);
    } else if (v >= 30) {
      // 30-50: red → yellow
      return this.lerpHex(GRAD_RED, GRAD_YELLOW, (v - 30) / 20);
    } else {
      // 0-30: deep red
      return this.lerpHex(GRAD_RED, GRAD_YELLOW, v / 30 * 0.3);
    }
  }

  /** Linear interpolate between two hex colors. t in [0,1]. */
  private lerpHex(a: string, b: string, t: number): string {
    const ar = parseInt(a.slice(1, 3), 16);
    const ag = parseInt(a.slice(3, 5), 16);
    const ab = parseInt(a.slice(5, 7), 16);
    const br = parseInt(b.slice(1, 3), 16);
    const bg = parseInt(b.slice(3, 5), 16);
    const bb = parseInt(b.slice(5, 7), 16);
    const r = Math.round(ar + (br - ar) * t);
    const g = Math.round(ag + (bg - ag) * t);
    const bv = Math.round(ab + (bb - ab) * t);
    return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${bv.toString(16).padStart(2, '0')}`;
  }

  private toBarSpacing(zoomPercent: number): number {
    const normalized = Math.max(25, Math.min(400, zoomPercent));
    return BASE_BAR_SPACING * (normalized / 100);
  }
}
