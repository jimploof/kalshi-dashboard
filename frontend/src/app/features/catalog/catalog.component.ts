import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { EMPTY, catchError, switchMap } from 'rxjs';

import { CatalogService, EventDTO, MarketDetailDTO, MarketDTO, SeriesDTO } from './catalog.service';
import { CatalogStateService } from './catalog-state.service';
import { EventListComponent } from './components/event-list/event-list.component';
import { MarketDetailModalComponent } from './components/market-detail-modal/market-detail-modal.component';
import { MarketListComponent } from './components/market-list/market-list.component';
import { SeriesListComponent } from './components/series-list/series-list.component';

type CatalogView = 'welcome' | 'series' | 'events' | 'markets';
type SortKey = 'title_asc' | 'title_desc' | 'volume_desc' | 'volume_asc';

export const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'title_asc',   label: 'Title (A \u2192 Z)' },
  { value: 'title_desc',  label: 'Title (Z \u2192 A)' },
  { value: 'volume_desc', label: 'Volume (High \u2192 Low)' },
  { value: 'volume_asc',  label: 'Volume (Low \u2192 High)' },
];

@Component({
  selector: 'app-catalog',
  standalone: true,
  imports: [
    SeriesListComponent,
    EventListComponent,
    MarketListComponent,
    MarketDetailModalComponent,
  ],
  templateUrl: './catalog.component.html',
  styleUrl: './catalog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CatalogComponent {
  private readonly destroyRef   = inject(DestroyRef);
  private readonly service      = inject(CatalogService);
  readonly state                = inject(CatalogStateService);

  // ── Sort / search state (series view only) ────────────────────────────────
  readonly sortKey      = signal<SortKey>('volume_desc');
  readonly seriesSearch = signal('');
  readonly sortOptions  = SORT_OPTIONS;

  // ── Data signals ──────────────────────────────────────────────────────────
  readonly series         = signal<readonly SeriesDTO[]>([]);
  readonly seriesLoading  = signal(false);
  readonly events         = signal<readonly EventDTO[]>([]);
  readonly eventsLoading  = signal(false);
  readonly markets        = signal<readonly MarketDTO[]>([]);
  readonly marketsLoading = signal(false);

  // ── Modal signals ─────────────────────────────────────────────────────────
  readonly modalMarket    = signal<MarketDetailDTO | null>(null);
  readonly modalOpen      = signal(false);

  // ── View ──────────────────────────────────────────────────────────────────
  readonly currentView = computed<CatalogView>(() => {
    if (this.state.selectedEventTicker())  return 'markets';
    if (this.state.selectedSeriesTicker()) return 'events';
    if (this.state.selectedCategory())     return 'series';
    return 'welcome';
  });

  // ── Display list: sort + filter client-side — instant, zero re-fetch ──────────
  readonly displaySeries = computed(() => {
    const q              = this.seriesSearch().toLowerCase().trim();
    const [field, dir]   = this.sortKey().split('_') as [string, string];
    const asc            = dir === 'asc';

    let items: readonly SeriesDTO[] = this.series();

    if (q) {
      items = items.filter(s =>
        (s.ticker?.toLowerCase().includes(q)) ||
        (s.title?.toLowerCase().includes(q)) ||
        (s.tags?.some(t => t.toLowerCase().includes(q))),
      );
    }

    return [...items].sort((a, b) => {
      if (field === 'volume') {
        const av = a.volume ?? (asc ? Infinity : -Infinity);
        const bv = b.volume ?? (asc ? Infinity : -Infinity);
        return asc ? av - bv : bv - av;
      }
      const at = (a.title ?? a.ticker ?? '').toLowerCase();
      const bt = (b.title ?? b.ticker ?? '').toLowerCase();
      return asc ? at.localeCompare(bt) : bt.localeCompare(at);
    });
  });

  constructor() {
    // Level 1: category change → load series with volumes; all sorting is client-side after
    toObservable(this.state.selectedCategory).pipe(
      switchMap(category => {
        this.series.set([]);
        if (!category) { this.seriesLoading.set(false); return EMPTY; }
        this.seriesLoading.set(true);
        return this.service.getSeries(category).pipe(
          catchError(() => { this.seriesLoading.set(false); return EMPTY; }),
        );
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(r => {
      this.series.set(r.series);
      this.seriesLoading.set(false);
    });

    // Reset search when the user switches category
    effect(() => {
      this.state.selectedCategory();
      untracked(() => this.seriesSearch.set(''));
    });

    // Level 2: seriesTicker → load events
    toObservable(this.state.selectedSeriesTicker).pipe(
      switchMap(ticker => {
        this.events.set([]);
        if (!ticker) { this.eventsLoading.set(false); return EMPTY; }
        this.eventsLoading.set(true);
        return this.service.getEvents(ticker, 'open').pipe(
          catchError(() => { this.eventsLoading.set(false); return EMPTY; }),
        );
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(r => {
      this.events.set(r.events);
      this.eventsLoading.set(false);
    });

    // Level 3: eventTicker → load event detail → extract markets
    toObservable(this.state.selectedEventTicker).pipe(
      switchMap(ticker => {
        this.markets.set([]);
        if (!ticker) { this.marketsLoading.set(false); return EMPTY; }
        this.marketsLoading.set(true);
        return this.service.getEventDetail(ticker).pipe(
          catchError(() => { this.marketsLoading.set(false); return EMPTY; }),
        );
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(r => {
      this.markets.set(r.event?.markets ?? []);
      this.marketsLoading.set(false);
    });
  }

  onSeriesSelected(ticker: string): void {
    this.state.selectSeries(ticker);
  }

  onEventSelected(ticker: string): void {
    this.state.selectEvent(ticker);
  }

  onMarketSelected(ticker: string): void {
    this.service.getMarketDetail(ticker).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(r => {
      if (r.market) {
        this.modalMarket.set(r.market);
        this.modalOpen.set(true);
      }
    });
  }

  closeModal(): void {
    this.modalOpen.set(false);
    this.modalMarket.set(null);
  }
}
