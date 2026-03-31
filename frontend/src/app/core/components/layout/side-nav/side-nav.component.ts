import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { interval, startWith, switchMap } from 'rxjs';
import { NgIconComponent, provideIcons } from '@ng-icons/core';
import {
  heroChevronDoubleLeft,
  heroChevronDoubleRight,
  heroChevronDown,
  heroChevronRight,
  heroSquares2x2,
  heroClipboardDocumentList,
  heroChartBar,
  heroCheckBadge,
  heroBolt,
} from '@ng-icons/heroicons/outline';

import { CatalogService, type CategorySummary, type LiveEventSummaryDTO } from '../../../../features/catalog/catalog.service';
import { CatalogStateService } from '../../../../features/catalog/catalog-state.service';

/** How often (ms) to refresh the live events list while sidebar is mounted. */
const LIVE_POLL_INTERVAL_MS = 60_000;

@Component({
  selector: 'app-side-nav',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, NgIconComponent],
  providers: [
    provideIcons({
      heroChevronDoubleLeft,
      heroChevronDoubleRight,
      heroChevronDown,
      heroChevronRight,
      heroSquares2x2,
      heroClipboardDocumentList,
      heroChartBar,
      heroCheckBadge,
      heroBolt,
    }),
  ],
  templateUrl: './side-nav.component.html',
  styleUrl: './side-nav.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SideNavComponent implements OnInit {
  private readonly catalogService = inject(CatalogService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly router = inject(Router);
  readonly state = inject(CatalogStateService);

  readonly collapsed = signal(false);
  readonly categories = signal<readonly CategorySummary[]>([]);
  readonly categoriesLoading = signal(true);
  readonly catalogExpanded = signal(true);

  readonly liveEvents = signal<readonly LiveEventSummaryDTO[]>([]);
  readonly liveLoading = signal(true);
  readonly liveExpanded = signal(true);

  ngOnInit(): void {
    this.catalogService
      .getCategories()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: r => {
          this.categories.set(r.categories);
          this.categoriesLoading.set(false);
        },
        error: () => this.categoriesLoading.set(false),
      });

    interval(LIVE_POLL_INTERVAL_MS)
      .pipe(
        startWith(0),
        switchMap(() => this.catalogService.getLiveEvents()),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: r => {
          this.liveEvents.set(r.events);
          this.liveLoading.set(false);
        },
        error: () => this.liveLoading.set(false),
      });
  }

  toggle(): void {
    this.collapsed.update(v => !v);
  }

  toggleCatalog(): void {
    this.catalogExpanded.update(v => !v);
  }

  toggleLive(): void {
    this.liveExpanded.update(v => !v);
  }

  selectCategory(name: string): void {
    this.state.selectCategory(name);
    if (this.collapsed()) {
      this.collapsed.set(false);
    }
  }

  selectLiveEvent(event: LiveEventSummaryDTO): void {
    if (this.collapsed()) {
      this.collapsed.set(false);
    }
    if (event.first_market_ticker) {
      this.router.navigate(['/market', event.first_market_ticker]);
    } else {
      // Fall back to catalog with the event's category selected
      if (event.category) {
        this.state.selectCategory(event.category);
      }
      this.router.navigate(['/catalog']);
    }
  }

  /** Format the time remaining until a close_time ISO string as a compact label. */
  timeUntil(closeTime: string | null | undefined): string {
    if (!closeTime) return '';
    const diffMs = new Date(closeTime).getTime() - Date.now();
    if (diffMs <= 0) return 'closing';
    const totalMin = Math.floor(diffMs / 60_000);
    if (totalMin < 60) return `${totalMin}m`;
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    return m > 0 ? `${h}h ${m}m` : `${h}h`;
  }
}
