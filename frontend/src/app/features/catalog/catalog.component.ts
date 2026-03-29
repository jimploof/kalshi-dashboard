import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { EMPTY, catchError, switchMap, take } from 'rxjs';

import {
  CatalogService,
  EventCardSortBy,
  EventCardSummaryDTO,
  MarketDetailDTO,
  MarketDTO,
  SortOrder,
} from './catalog.service';
import { CatalogStateService } from './catalog-state.service';
import { EventCardListComponent } from './components/event-card-list/event-card-list.component';
import { MarketDetailModalComponent } from './components/market-detail-modal/market-detail-modal.component';
import { MarketListComponent } from './components/market-list/market-list.component';

type CatalogView = 'welcome' | 'event-cards' | 'markets';

type SortOption = {
  readonly sortBy: EventCardSortBy;
  readonly sortOrder: SortOrder;
  readonly label: string;
  readonly key: string;
};

const SORT_OPTIONS: readonly SortOption[] = [
  { sortBy: 'total_volume',        sortOrder: 'desc', label: 'Volume (High \u2192 Low)',         key: 'total_volume:desc' },
  { sortBy: 'total_volume',        sortOrder: 'asc',  label: 'Volume (Low \u2192 High)',          key: 'total_volume:asc'  },
  { sortBy: 'total_open_interest', sortOrder: 'desc', label: 'Open Interest (High \u2192 Low)',   key: 'total_open_interest:desc' },
  { sortBy: 'nearest_close_time',  sortOrder: 'asc',  label: 'Closing Soon',                      key: 'nearest_close_time:asc' },
  { sortBy: 'title',               sortOrder: 'asc',  label: 'Title (A \u2192 Z)',                key: 'title:asc' },
  { sortBy: 'title',               sortOrder: 'desc', label: 'Title (Z \u2192 A)',                key: 'title:desc' },
] as const;

@Component({
  selector: 'app-catalog',
  standalone: true,
  imports: [
    EventCardListComponent,
    MarketListComponent,
    MarketDetailModalComponent,
  ],
  templateUrl: './catalog.component.html',
  styleUrl: './catalog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CatalogComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly service    = inject(CatalogService);
  readonly state              = inject(CatalogStateService);

  // ── Sort state ─────────────────────────────────────────────────────────────
  readonly sortBy      = signal<EventCardSortBy>('total_volume');
  readonly sortOrder   = signal<SortOrder>('desc');
  readonly sortOptions = SORT_OPTIONS;

  /** Single key representing the current sort selection, used to drive <select>. */
  readonly sortKey = computed(() => `${this.sortBy()}:${this.sortOrder()}`);

  // ── Derived browse key — changes whenever category OR sort changes ─────────
  private readonly _browseKey = computed(() => {
    const category = this.state.selectedCategory();
    if (!category) return null;
    return { category, sortBy: this.sortBy(), sortOrder: this.sortOrder() };
  });

  // ── Event-cards data signals ───────────────────────────────────────────────
  readonly cards        = signal<readonly EventCardSummaryDTO[]>([]);
  readonly cardsLoading = signal(false);
  readonly nextCursor   = signal<string | null>(null);
  readonly total        = signal(0);
  readonly stale        = signal(false);

  // ── Markets drill-in signals ───────────────────────────────────────────────
  readonly markets        = signal<readonly MarketDTO[]>([]);
  readonly marketsLoading = signal(false);

  // ── Modal signals ──────────────────────────────────────────────────────────
  readonly modalMarket = signal<MarketDetailDTO | null>(null);
  readonly modalOpen   = signal(false);

  // ── View ───────────────────────────────────────────────────────────────────
  readonly currentView = computed<CatalogView>(() => {
    if (this.state.selectedEventTicker()) return 'markets';
    if (this.state.selectedCategory())    return 'event-cards';
    return 'welcome';
  });

  constructor() {
    // Level 1: category + sort changes → fetch first page of event cards.
    // switchMap cancels the in-flight request when category or sort changes.
    toObservable(this._browseKey).pipe(
      switchMap(key => {
        this.cards.set([]);
        this.nextCursor.set(null);
        this.stale.set(false);
        if (!key) {
          this.cardsLoading.set(false);
          return EMPTY;
        }
        this.cardsLoading.set(true);
        return this.service.getEventCards(key.category, {
          sortBy: key.sortBy,
          sortOrder: key.sortOrder,
          limit: 24,
        }).pipe(
          catchError(() => { this.cardsLoading.set(false); return EMPTY; }),
        );
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(r => {
      this.cards.set(r.cards ?? []);
      this.nextCursor.set(r.next_cursor ?? null);
      this.total.set(r.total);
      this.stale.set(r.stale);
      this.cardsLoading.set(false);
    });

    // Level 2: event card → load event detail → extract inline markets.
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

  setSortKey(key: string): void {
    const opt = SORT_OPTIONS.find(o => o.key === key);
    if (opt) {
      this.sortBy.set(opt.sortBy);
      this.sortOrder.set(opt.sortOrder);
      // _browseKey computed updates automatically, triggering a fresh fetch.
    }
  }

  loadMore(): void {
    const cursor   = this.nextCursor();
    const category = this.state.selectedCategory();
    if (!cursor || !category || this.cardsLoading()) return;
    this.cardsLoading.set(true);
    this.service.getEventCards(category, {
      sortBy:    this.sortBy(),
      sortOrder: this.sortOrder(),
      limit:     24,
      cursor,
    }).pipe(
      take(1),
      catchError(() => { this.cardsLoading.set(false); return EMPTY; }),
    ).subscribe(r => {
      this.cards.update(existing => [...existing, ...(r.cards ?? [])]);
      this.nextCursor.set(r.next_cursor ?? null);
      this.total.set(r.total);
      this.stale.set(r.stale);
      this.cardsLoading.set(false);
    });
  }

  onEventCardSelected(ticker: string): void {
    this.state.selectEvent(ticker);
  }

  onMarketSelected(ticker: string): void {
    this.service.getMarketDetail(ticker).pipe(
      take(1),
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
