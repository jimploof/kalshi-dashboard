import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../../core/services/api.service';
import type { components } from '../../core/types/api.generated';

// ─── Convenience type aliases (sourced from generated OpenAPI schema) ─────────
export type CategoriesResponse    = components['schemas']['CategoriesResponse'];
export type CategorySummary       = components['schemas']['CategorySummary'];
export type CatalogSeriesResponse = components['schemas']['CatalogSeriesResponse'];
export type SeriesDTO             = components['schemas']['SeriesDTO'];
export type CatalogEventsResponse = components['schemas']['CatalogEventsResponse'];
export type EventDTO              = components['schemas']['EventDTO'];
export type CatalogEventDetailResponse  = components['schemas']['CatalogEventDetailResponse'];
export type MarketDTO             = components['schemas']['MarketDTO'];
export type MarketDetailDTO       = components['schemas']['MarketDetailDTO'];
export type CatalogMarketDetailResponse = components['schemas']['CatalogMarketDetailResponse'];

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

  getEventDetail(ticker: string): Observable<CatalogEventDetailResponse> {
    return this.api.get<CatalogEventDetailResponse>(`/catalog/events/${encodeURIComponent(ticker)}`);
  }

  getMarketDetail(ticker: string): Observable<CatalogMarketDetailResponse> {
    return this.api.get<CatalogMarketDetailResponse>(`/catalog/markets/${encodeURIComponent(ticker)}`);
  }
}
