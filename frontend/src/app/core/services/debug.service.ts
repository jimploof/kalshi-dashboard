import { inject, Injectable, signal } from '@angular/core';
import { interval, Subscription } from 'rxjs';
import { catchError, of, switchMap } from 'rxjs';

import { ApiService } from './api.service';

export type KalshiCallRecord = {
  readonly endpoint: string;
  readonly started_at: string;
  readonly finished_at: string | null;
  readonly elapsed_ms: number | null;
  readonly status_code: number | null;
  readonly error: string | null;
};

export type CacheLookupRecord = {
  readonly timestamp: string;
  readonly hit: boolean;
  readonly snapshot_id: string | null;
  readonly snapshot_age_seconds: number | null;
  readonly was_stale: boolean;
  readonly was_discarded: boolean;
};

export type SnapshotBuildRecord = {
  readonly started_at: string;
  readonly finished_at: string | null;
  readonly elapsed_seconds: number;
  readonly in_progress: boolean;
  readonly pages_fetched: number;
  readonly events_processed: number;
  readonly markets_processed: number;
  readonly error: string | null;
};

export type ConnectivityStatus = {
  readonly rest_url: string;
  readonly rest_configured: boolean;
  readonly rest_status: 'active' | 'error' | 'no_calls';
  readonly rest_last_call_at: string | null;
  readonly rest_last_status_code: number | null;
  readonly ws_url: string;
  readonly ws_configured: boolean;
  readonly ws_connected: boolean;
  readonly ws_subscribed_tickers: readonly string[];
  readonly ws_frontend_clients: Readonly<Record<string, number>>;
};

export type DebugStatus = {
  readonly debug_mode: boolean;
  readonly server_time_utc: string;
  readonly connectivity: ConnectivityStatus | null;
  readonly event_card_refresh_in_progress: boolean;
  readonly snapshot_metrics: SnapshotBuildRecord | null;
  readonly recent_kalshi_calls: readonly KalshiCallRecord[];
  readonly recent_cache_lookups: readonly CacheLookupRecord[];
  readonly snapshot_builds: readonly SnapshotBuildRecord[];
};

const POLL_INTERVAL_MS = 2000;

@Injectable({ providedIn: 'root' })
export class DebugService {
  private readonly api = inject(ApiService);

  readonly status = signal<DebugStatus | null>(null);
  readonly debugMode = signal<boolean>(false);

  private _pollSub: Subscription | null = null;

  /** Start polling /api/debug/status. Safe to call multiple times. */
  startPolling(): void {
    if (this._pollSub) return;
    this._pollSub = interval(POLL_INTERVAL_MS)
      .pipe(
        switchMap(() =>
          this.api.get<DebugStatus>('/debug/status').pipe(catchError(() => of(null))),
        ),
      )
      .subscribe((result) => {
        if (result !== null) {
          this.status.set(result);
          this.debugMode.set(result.debug_mode);
        }
      });

    // Fetch immediately without waiting for the first interval tick.
    this.api
      .get<DebugStatus>('/debug/status')
      .pipe(catchError(() => of(null)))
      .subscribe((result) => {
        if (result !== null) {
          this.status.set(result);
          this.debugMode.set(result.debug_mode);
        }
      });
  }

  stopPolling(): void {
    this._pollSub?.unsubscribe();
    this._pollSub = null;
  }
}
