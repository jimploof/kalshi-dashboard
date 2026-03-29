import { Injectable, signal } from '@angular/core';

/**
 * Catalog drill-down state — shared between SideNavComponent (category
 * selection) and CatalogComponent (data loading + breadcrumb).
 *
 * All state is held in writable Signals.  Mutation methods cascade resets
 * downward so the view always reflects a consistent drill-down position.
 */
@Injectable({ providedIn: 'root' })
export class CatalogStateService {
  readonly selectedCategory      = signal<string | null>(null);
  readonly selectedSeriesTicker  = signal<string | null>(null);
  readonly selectedEventTicker   = signal<string | null>(null);

  selectCategory(category: string): void {
    this.selectedCategory.set(category);
    this.selectedSeriesTicker.set(null);
    this.selectedEventTicker.set(null);
  }

  selectSeries(ticker: string): void {
    this.selectedSeriesTicker.set(ticker);
    this.selectedEventTicker.set(null);
  }

  selectEvent(ticker: string): void {
    this.selectedEventTicker.set(ticker);
  }

  resetToRoot(): void {
    this.selectedCategory.set(null);
    this.selectedSeriesTicker.set(null);
    this.selectedEventTicker.set(null);
  }

  resetToCategory(): void {
    this.selectedSeriesTicker.set(null);
    this.selectedEventTicker.set(null);
  }

  resetToSeries(): void {
    this.selectedEventTicker.set(null);
  }
}
