/**
 * EventChartComponent — multi-outcome line chart using TradingView Lightweight Charts.
 *
 * Renders one line per event outcome (sibling market) on a shared time axis.
 * Each line shows the close price history for that outcome, colour-coded.
 *
 * Usage:
 *  <app-event-chart [outcomes]="outcomeSeries()" />
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
  ColorType,
  createChart,
  CrosshairMode,
  IChartApi,
  ISeriesApi,
  UTCTimestamp,
} from 'lightweight-charts';

import type { CandlestickDTO } from '../market.service';
import { BlipMarkerComponent } from '../blip-marker/blip-marker.component';

/** A single outcome's data for the event chart. */
export type OutcomeLine = {
  readonly ticker: string;
  readonly label: string;
  readonly color: string;
  readonly candlesticks: readonly CandlestickDTO[];
};

/** Dark workstation palette. */
const PALETTE = {
  bg:     '#0d1117',
  grid:   '#1c2128',
  text:   '#c9d1d9',
  border: '#21262d',
} as const;

/** Distinct outcome colours — up to 6 outcomes supported visually. */
const OUTCOME_COLORS = [
  '#3b82f6', // blue
  '#f59e0b', // amber
  '#10b981', // emerald
  '#8b5cf6', // violet
  '#ec4899', // pink
  '#06b6d4', // cyan
] as const;
const BASE_BAR_SPACING = 6;

/** Get the colour for an outcome by index. */
export function outcomeColor(index: number): string {
  return OUTCOME_COLORS[index % OUTCOME_COLORS.length];
}

@Component({
  selector: 'app-event-chart',
  standalone: true,
  imports: [BlipMarkerComponent],
  templateUrl: './event-chart.component.html',
  styleUrl: './event-chart.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EventChartComponent implements AfterViewInit, OnDestroy {
  // ── Inputs ────────────────────────────────────────────────────────────────
  readonly outcomes = input<readonly OutcomeLine[]>([]);
  readonly livePrices = input<Readonly<Record<string, number | null>>>({});
  readonly liveTick = input<number>(0);
  readonly periodInterval = input<number>(1);
  readonly zoomPercent = input<number>(100);

  // ── DOM reference ─────────────────────────────────────────────────────────
  readonly containerRef = viewChild.required<ElementRef<HTMLDivElement>>('chartContainer');

  readonly blips = signal<readonly BlipPoint[]>([]);

  // ── Chart state ───────────────────────────────────────────────────────────
  private chart: IChartApi | null = null;
  private lineSeries: ISeriesApi<'Line'>[] = [];
  private yAxisAnchorSeries: ISeriesApi<'Line'> | null = null;
  private readonly lineSeriesByTicker = new Map<string, ISeriesApi<'Line'>>();
  private readonly liveBarsByTicker = new Map<string, { ts: number; open: number; close: number }>();
  private readonly lastPointByTicker = new Map<string, { ts: number; price: number; color: string }>();
  private resizeObserver: ResizeObserver | null = null;
  private blipRaf: number | null = null;

  constructor() {
    effect(() => {
      const data = this.outcomes();
      if (this.chart) {
        this.updateSeries(data);
      }
    });

    effect(() => {
      const zoom = this.zoomPercent();
      if (this.chart) {
        this.chart.timeScale().applyOptions({
          barSpacing: this.toBarSpacing(zoom),
        });
        this.chart.timeScale().scrollToPosition(0, false);
        this.updateYAxisAnchor(untracked(() => this.outcomes()));
        this.queueBlipRecompute();
      }
    });

    // Update all visible event lines on every incoming ticker pulse.
    effect(() => {
      this.liveTick();

      if (!this.chart || this.lineSeriesByTicker.size === 0) return;

      const livePrices = this.livePrices();
      const periodSecs = this.periodInterval() * 60;
      const nowSecs = Math.floor(Date.now() / 1000);
      const barTs = Math.floor(nowSecs / periodSecs) * periodSecs;

      for (const [ticker, series] of this.lineSeriesByTicker) {
        const price = livePrices[ticker];
        if (price === null || price === undefined) continue;

        const existing = this.liveBarsByTicker.get(ticker);
        if (!existing || existing.ts !== barTs) {
          this.liveBarsByTicker.set(ticker, { ts: barTs, open: price, close: price });
        } else {
          existing.close = price;
        }

        series.update({ time: barTs as UTCTimestamp, value: price });
        const color = this.lastPointByTicker.get(ticker)?.color ?? '#5c9dff';
        this.lastPointByTicker.set(ticker, { ts: barTs, price, color });
      }

      this.queueBlipRecompute();

    });
  }

  ngAfterViewInit(): void {
    this.initChart();
  }

  ngOnDestroy(): void {
    if (this.blipRaf !== null) {
      cancelAnimationFrame(this.blipRaf);
      this.blipRaf = null;
    }
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
        scaleMargins: { top: 0.05, bottom: 0.05 },
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

    const initialData = this.outcomes();
    if (initialData.length) {
      this.updateSeries(initialData);
    }

    requestAnimationFrame(() => {
      if (this.chart && container.clientHeight > 0) {
        this.chart.applyOptions({
          width: container.clientWidth,
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
        this.queueBlipRecompute();
      }
    });
    this.resizeObserver.observe(container);
  }

  // ── Series management ─────────────────────────────────────────────────────

  private updateSeries(outcomes: readonly OutcomeLine[]): void {
    if (!this.chart) return;

    // Remove existing series.
    for (const s of this.lineSeries) {
      this.chart.removeSeries(s);
    }
    this.lineSeries = [];
    this.lineSeriesByTicker.clear();
    this.liveBarsByTicker.clear();
    this.lastPointByTicker.clear();

    // autoscaleInfoProvider locks Y axis to 0-100 cents on every series.
    // margins must be 0 — non-zero adds that fraction of the 100-unit range
    // as padding (e.g. 0.05 = 5 units), which causes the axis to show -5.
    const autoscaleInfoProvider = () => ({
      priceRange: { minValue: 0, maxValue: 100 },
      margins: { above: 0, below: 0 },
    });

    // Create one line series per outcome.
    for (const outcome of outcomes) {
      const series = this.chart.addLineSeries({
        color: outcome.color,
        lineWidth: 2,
        lastValueVisible: true,
        priceLineVisible: false,
        crosshairMarkerVisible: true,
        priceFormat: { type: 'price', precision: 0, minMove: 1 },
        autoscaleInfoProvider,
      });

      // Filter out ghost bars where no trades occurred (close=0, volume=0).
      // Kalshi returns candle frames for every period even without activity;
      // our backend converts null prices to 0.  Plotting those as real price
      // points causes the line to spike down to 0.
      const data = outcome.candlesticks;
      const active = data.filter(c => c.close > 0 || c.volume > 0);

      series.setData(
        active.map(c => ({
          time: c.ts as UTCTimestamp,
          value: c.close,
        })),
      );

      this.lineSeries.push(series);
      this.lineSeriesByTicker.set(outcome.ticker, series);

      const last = active[active.length - 1];
      if (last) {
        this.lastPointByTicker.set(outcome.ticker, {
          ts: last.ts,
          price: last.close,
          color: outcome.color,
        });
      }
    }

    this.updateYAxisAnchor(outcomes);
    this.queueBlipRecompute();
    this.chart.timeScale().scrollToPosition(0, false);
  }

  private updateYAxisAnchor(_outcomes: readonly OutcomeLine[]): void {
    // Y-axis range is now locked via autoscaleInfoProvider on each line series.
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

  private queueBlipRecompute(): void {
    if (this.blipRaf !== null) {
      cancelAnimationFrame(this.blipRaf);
    }
    this.blipRaf = requestAnimationFrame(() => {
      this.blipRaf = null;
      this.recomputeBlips();
    });
  }

  private recomputeBlips(): void {
    if (!this.chart) {
      this.blips.set([]);
      return;
    }

    const next: BlipPoint[] = [];
    for (const [ticker, point] of this.lastPointByTicker.entries()) {
      const series = this.lineSeriesByTicker.get(ticker);
      if (!series) continue;

      const x = this.chart.timeScale().timeToCoordinate(point.ts as UTCTimestamp);
      const y = series.priceToCoordinate(point.price);
      if (x === null || y === null) continue;

      next.push({
        ticker,
        x,
        y,
        colorRgb: hexToRgb(point.color) ?? '92, 157, 255',
      });
    }

    this.blips.set(next);
  }
}

type BlipPoint = {
  readonly ticker: string;
  readonly x: number;
  readonly y: number;
  readonly colorRgb: string;
};

function hexToRgb(hex: string): string | null {
  const normalized = hex.replace('#', '');
  if (normalized.length !== 6) return null;
  const value = Number.parseInt(normalized, 16);
  if (Number.isNaN(value)) return null;
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `${r}, ${g}, ${b}`;
}
