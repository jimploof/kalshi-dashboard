/**
 * Market service — wraps ApiService with typed calls to the backend
 * /api/market/* endpoints for the trading view panel.
 *
 * NOTE: Types below are defined locally because the backend endpoints were
 * added alongside this frontend code.  Run `npm run generate:types` after the
 * backend is deployed to regenerate src/app/core/types/api.generated.ts and
 * replace the local type definitions with generated aliases.
 */
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../../core/services/api.service';

// ---------------------------------------------------------------------------
// Market detail DTO
// (mirrors backend MarketDetailDTO — regenerate from OpenAPI after deploy)
// ---------------------------------------------------------------------------

export type MarketViewDTO = {
  readonly ticker: string;
  readonly series_ticker: string | null;
  readonly event_ticker: string | null;
  readonly market_type: string | null;
  readonly yes_sub_title: string | null;
  readonly no_sub_title: string | null;
  readonly title: string | null;
  readonly subtitle: string | null;
  readonly status: string | null;
  readonly result: string | null;
  readonly open_time: string | null;
  readonly close_time: string | null;
  readonly yes_bid_dollars: string | null;
  readonly yes_ask_dollars: string | null;
  readonly last_price_dollars: string | null;
  readonly volume_fp: string | null;
  readonly volume_24h_fp: string | null;
  readonly open_interest_fp: string | null;
  readonly previous_yes_bid_dollars: string | null;
  readonly previous_yes_ask_dollars: string | null;
  readonly previous_price_dollars: string | null;
  readonly notional_value_dollars: string | null;
  readonly settlement_value_dollars: string | null;
  readonly settlement_ts: string | null;
  readonly strike_type: string | null;
  readonly floor_strike: number | null;
  readonly cap_strike: number | null;
  readonly rules_primary: string | null;
  readonly rules_secondary: string | null;
  readonly is_provisional: boolean | null;
  readonly fractional_trading_enabled: boolean | null;
};

export type MarketViewResponse = {
  readonly status: string;
  readonly market: MarketViewDTO | null;
};

// ---------------------------------------------------------------------------
// Candlestick DTO
// ---------------------------------------------------------------------------

export type CandlestickDTO = {
  readonly ts: number;    // end_period_ts (Unix seconds)
  readonly open: number;  // cents 0–100
  readonly high: number;
  readonly low: number;
  readonly close: number;
  readonly volume: number;
};

export type CandlesticksResponse = {
  readonly status: string;
  readonly ticker: string;
  readonly series_ticker: string;
  readonly period_interval: number;
  readonly candlesticks: readonly CandlestickDTO[];
};

// ---------------------------------------------------------------------------
// Orderbook DTO
// ---------------------------------------------------------------------------

export type OrderbookLevel = {
  readonly price: number;    // cents 0–100
  readonly quantity: number;
};

export type OrderbookResponse = {
  readonly status: string;
  readonly ticker: string;
  readonly yes: readonly OrderbookLevel[];
  readonly no: readonly OrderbookLevel[];
};

// ---------------------------------------------------------------------------
// Service
// ---------------------------------------------------------------------------

@Injectable({ providedIn: 'root' })
export class MarketService {
  private readonly api = inject(ApiService);

  /** Full market detail snapshot for the trading view bootstrap. */
  getMarket(ticker: string): Observable<MarketViewResponse> {
    return this.api.get<MarketViewResponse>(
      `/market/${encodeURIComponent(ticker)}`,
    );
  }

  /** OHLCV candlestick history for a given time range and candle period. */
  getCandlesticks(
    ticker: string,
    opts: {
      readonly seriesTicker: string;
      readonly startTs: number;
      readonly endTs: number;
      readonly periodInterval?: number;
    },
  ): Observable<CandlesticksResponse> {
    const params = new URLSearchParams();
    params.set('series_ticker', opts.seriesTicker);
    params.set('start_ts', String(opts.startTs));
    params.set('end_ts', String(opts.endTs));
    if (opts.periodInterval !== undefined) {
      params.set('period_interval', String(opts.periodInterval));
    }
    return this.api.get<CandlesticksResponse>(
      `/market/${encodeURIComponent(ticker)}/candlesticks?${params.toString()}`,
    );
  }

  /** Current order book depth (REST snapshot; live updates come via WS). */
  getOrderbook(ticker: string, depth = 20): Observable<OrderbookResponse> {
    return this.api.get<OrderbookResponse>(
      `/market/${encodeURIComponent(ticker)}/orderbook?depth=${depth}`,
    );
  }
}
