import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { EMPTY, catchError, switchMap } from 'rxjs';

import {
  CatalogService,
  EventCardSortBy,
  EventCardSummaryDTO,
  MarketDTO,
  SortOrder,
} from './catalog.service';
import { CatalogStateService } from './catalog-state.service';
import { EventCardListComponent } from './components/event-card-list/event-card-list.component';
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
  ],
  templateUrl: './catalog.component.html',
  styleUrl: './catalog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CatalogComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly service    = inject(CatalogService);
  private readonly router     = inject(Router);
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
  readonly total        = signal(0);
  readonly stale        = signal(false);

  // ── Client-side search ─────────────────────────────────────────────────────
  readonly searchQuery = signal('');
  readonly filteredCards = computed(() => {
    const query = this.searchQuery().trim().toLowerCase();
    const all = this.cards();
    if (!query) return all;
    return all.filter(card => {
      const haystack = [
        card.title,
        card.sub_title,
        card.event_ticker,
        card.series_ticker,
        ...(card.top_markets ?? []).map(m => m.yes_sub_title),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(query);
    });
  });

  // ── Markets drill-in signals ───────────────────────────────────────────────
  readonly markets        = signal<readonly MarketDTO[]>([]);
  readonly marketsLoading = signal(false);

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
        this.searchQuery.set('');
        this.stale.set(false);
        if (!key) {
          this.cardsLoading.set(false);
          return EMPTY;
        }
        this.cardsLoading.set(true);
        return this.service.getEventCards(key.category, {
          sortBy: key.sortBy,
          sortOrder: key.sortOrder,
        }).pipe(
          catchError(() => { this.cardsLoading.set(false); return EMPTY; }),
        );
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(r => {
      this.cards.set(r.cards ?? []);
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

  setSearchQuery(query: string): void {
    this.searchQuery.set(query);
  }

  onEventCardSelected(ticker: string): void {
    this.state.selectEvent(ticker);
  }

  onMarketSelected(ticker: string): void {
    this.router.navigate(['/market', ticker]);
  }

  // closeModal is no longer used (modal replaced by market view route).
}
