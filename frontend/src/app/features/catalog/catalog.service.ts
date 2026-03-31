import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../../core/services/api.service';
import type { components, operations } from '../../core/types/api.generated';

// ─── Convenience type aliases (sourced from generated OpenAPI schema) ─────────
export type CategoriesResponse    = components['schemas']['CategoriesResponse'];
export type CategorySummary       = components['schemas']['CategorySummary'];
export type CatalogSeriesResponse = components['schemas']['CatalogSeriesResponse'];
export type SeriesDTO             = components['schemas']['SeriesDTO'];
export type CatalogEventCardsResponse = components['schemas']['CatalogEventCardsResponse'];
export type EventCardSummaryDTO       = components['schemas']['EventCardSummaryDTO'];
export type EventCardMarketSummaryDTO = components['schemas']['EventCardMarketSummaryDTO'];
export type CatalogEventsResponse = components['schemas']['CatalogEventsResponse'];
export type EventDTO              = components['schemas']['EventDTO'];
export type CatalogEventDetailResponse  = components['schemas']['CatalogEventDetailResponse'];
export type MarketDTO             = components['schemas']['MarketDTO'];
export type MarketDetailDTO       = components['schemas']['MarketDetailDTO'];
export type CatalogMarketDetailResponse = components['schemas']['CatalogMarketDetailResponse'];
export type LiveEventsResponse    = components['schemas']['LiveEventsResponse'];
export type LiveEventSummaryDTO   = components['schemas']['LiveEventSummaryDTO'];

// ─── Sort types derived from the generated OpenAPI operation contract ─────────
type _EventCardsQuery = operations['get_event_cards_api_catalog_event_cards_get']['parameters']['query'];
export type EventCardSortBy = NonNullable<_EventCardsQuery['sort_by']>;
export type SortOrder       = NonNullable<_EventCardsQuery['sort_order']>;

/**
 * Catalog service — wraps ApiService with typed calls to the backend
 * /api/catalog/* endpoints.
 *
 * All HTTP paths are proxy-relative (/catalog/...) so the Angular dev proxy
 * prepends /api and forwards to the backend container.  Components must never
 * call ApiService directly — only CatalogService.
 */
@Injectable({ providedIn: 'root' })
export class CatalogService {
  private readonly api = inject(ApiService);

  getCategories(): Observable<CategoriesResponse> {
    return this.api.get<CategoriesResponse>('/catalog/categories');
  }

  getSeries(
    category?: string | null,
  ): Observable<CatalogSeriesResponse> {
    const params = new URLSearchParams();
    if (category) params.set('category', category);
    params.set('include_volume', 'true');
    return this.api.get<CatalogSeriesResponse>(`/catalog/series?${params.toString()}`);
  }

  getEvents(seriesTicker: string, status = 'open', limit = 50): Observable<CatalogEventsResponse> {
    return this.api.get<CatalogEventsResponse>(
      `/catalog/events?series_ticker=${encodeURIComponent(seriesTicker)}&status=${status}&limit=${limit}`,
    );
  }

  getEventCards(
    category: string,
    options?: {
      readonly seriesTicker?: string | null;
      readonly sortBy?: 'total_volume' | 'total_open_interest' | 'nearest_close_time' | 'title';
      readonly sortOrder?: 'asc' | 'desc';
      readonly limit?: number;
      readonly cursor?: string | null;
    },
  ): Observable<CatalogEventCardsResponse> {
    const params = new URLSearchParams();
    params.set('category', category);
    if (options?.seriesTicker) params.set('series_ticker', options.seriesTicker);
    if (options?.sortBy) params.set('sort_by', options.sortBy);
    if (options?.sortOrder) params.set('sort_order', options.sortOrder);
    if (options?.limit !== undefined) params.set('limit', String(options.limit));
    if (options?.cursor) params.set('cursor', options.cursor);
    return this.api.get<CatalogEventCardsResponse>(`/catalog/event-cards?${params.toString()}`);
  }

  getEventDetail(ticker: string): Observable<CatalogEventDetailResponse> {
    return this.api.get<CatalogEventDetailResponse>(`/catalog/events/${encodeURIComponent(ticker)}`);
  }

  getMarketDetail(ticker: string): Observable<CatalogMarketDetailResponse> {
    return this.api.get<CatalogMarketDetailResponse>(`/catalog/markets/${encodeURIComponent(ticker)}`);
  }

  getLiveEvents(windowHours = 24): Observable<LiveEventsResponse> {
    return this.api.get<LiveEventsResponse>(`/catalog/events/live?window_hours=${windowHours}`);
  }
}
