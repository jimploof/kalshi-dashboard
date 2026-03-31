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

/** Get the colour for an outcome by index. */
export function outcomeColor(index: number): string {
  return OUTCOME_COLORS[index % OUTCOME_COLORS.length];
}

@Component({
  selector: 'app-event-chart',
  standalone: true,
  imports: [],
  templateUrl: './event-chart.component.html',
  styleUrl: './event-chart.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EventChartComponent implements AfterViewInit, OnDestroy {
  // ── Inputs ────────────────────────────────────────────────────────────────
  readonly outcomes = input<readonly OutcomeLine[]>([]);

  // ── DOM reference ─────────────────────────────────────────────────────────
  readonly containerRef = viewChild.required<ElementRef<HTMLDivElement>>('chartContainer');

  // ── Chart state ───────────────────────────────────────────────────────────
  private chart: IChartApi | null = null;
  private lineSeries: ISeriesApi<'Line'>[] = [];
  private resizeObserver: ResizeObserver | null = null;

  constructor() {
    effect(() => {
      const data = this.outcomes();
      if (this.chart) {
        this.updateSeries(data);
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
        scaleMargins: { top: 0.05, bottom: 0.05 },
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

    // Create one line series per outcome.
    for (const outcome of outcomes) {
      const series = this.chart.addLineSeries({
        color: outcome.color,
        lineWidth: 2,
        lastValueVisible: true,
        priceLineVisible: false,
        crosshairMarkerVisible: true,
        priceFormat: { type: 'price', precision: 0, minMove: 1 },
        title: outcome.label,
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
    }

    this.chart.timeScale().scrollToRealTime();
  }
}
