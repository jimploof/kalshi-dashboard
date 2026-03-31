/**
 * MarketWsService — manages the WebSocket connection lifecycle for a single
 * market's live data stream.
 *
 * Scoped to the MarketViewComponent (listed in its `providers` array so each
 * component instance gets its own service instance).  Angular calls
 * ngOnDestroy when the component is destroyed, which closes the WebSocket and
 * stops all live updates automatically.
 *
 * The service:
 *  - connects to /ws/market/{ticker} via the Angular dev proxy
 *  - parses Kalshi WS v2 messages (ticker updates, orderbook snapshots/deltas)
 *  - maintains reactive orderbook state via Signals
 *  - exposes computed sorted bid/ask levels for direct template binding
 */
import { computed, Injectable, OnDestroy, signal } from '@angular/core';

// ---------------------------------------------------------------------------
// WS message shapes (Kalshi WS v2)
// ---------------------------------------------------------------------------

export type WsTickerMsg = {
  readonly market_ticker: string;
  readonly yes_bid: number | null;
  readonly yes_ask: number | null;
  readonly last_price: number | null;
  readonly last_size: number | null;
  readonly volume: number | null;
  readonly open_interest: number | null;
};

export type WsOrderbookSnapshot = {
  readonly market_ticker: string;
  readonly yes: readonly [number, number][];  // [price_cents, quantity]
  readonly no: readonly [number, number][];
};

export type WsOrderbookDelta = {
  readonly market_ticker: string;
  readonly price: number;    // cents
  readonly delta: number;    // positive = add, negative = remove
  readonly side: 'yes' | 'no';
};

type WsEnvelope = {
  readonly type: string;
  readonly sid?: number;
  readonly seq?: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  readonly msg?: any;
};

// ---------------------------------------------------------------------------
// Service
// ---------------------------------------------------------------------------

@Injectable()
export class MarketWsService implements OnDestroy {
  private ws: WebSocket | null = null;

  // ── Connection state ───────────────────────────────────────────────────────
  readonly connected = signal(false);
  readonly wsError = signal<string | null>(null);

  // ── Live ticker (from 'ticker' WS messages) ───────────────────────────────
  readonly yesBid = signal<number | null>(null);
  readonly yesAsk = signal<number | null>(null);
  readonly lastPrice = signal<number | null>(null);
  readonly volume = signal<number | null>(null);
  readonly openInterest = signal<number | null>(null);

  // ── Raw orderbook maps (price → quantity) ─────────────────────────────────
  private readonly _yesBook = signal<ReadonlyMap<number, number>>(new Map());
  private readonly _noBook = signal<ReadonlyMap<number, number>>(new Map());

  /**
   * YES bids sorted descending by price (best bid first), max 20 levels.
   * Tuple: [price_cents, quantity].
   */
  readonly yesBids = computed((): readonly [number, number][] =>
    [...this._yesBook().entries()]
      .filter(([, qty]) => qty > 0)
      .sort(([a], [b]) => b - a)
      .slice(0, 20) as [number, number][],
  );

  /**
   * NO bids sorted descending by price (best NO bid first), max 20 levels.
   * Tuple: [price_cents, quantity].
   */
  readonly noBids = computed((): readonly [number, number][] =>
    [...this._noBook().entries()]
      .filter(([, qty]) => qty > 0)
      .sort(([a], [b]) => b - a)
      .slice(0, 20) as [number, number][],
  );

  /** Implied spread in cents: 100 - best_yes_bid - best_no_bid. */
  readonly spread = computed((): number | null => {
    const yesBids = this.yesBids();
    const noBids = this.noBids();
    if (yesBids.length === 0 || noBids.length === 0) return null;
    return 100 - yesBids[0][0] - noBids[0][0];
  });

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  connect(ticker: string): void {
    if (this.ws && this.ws.readyState < WebSocket.CLOSING) {
      return;
    }
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${location.host}/ws/market/${encodeURIComponent(ticker)}`;
    this.ws = new WebSocket(url);
    this.ws.onopen = () => {
      this.connected.set(true);
      this.wsError.set(null);
    };
    this.ws.onclose = () => this.connected.set(false);
    this.ws.onerror = () => this.wsError.set('WebSocket connection failed');
    this.ws.onmessage = (event: MessageEvent<string>) => {
      this.handleMessage(event.data);
    };
  }

  disconnect(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.connected.set(false);
  }

  /**
   * Seed the order book from a REST snapshot before WS deltas begin arriving.
   * Called immediately after the initial getOrderbook() REST call resolves.
   * WS orderbook_snapshot and orderbook_delta messages continue to update
   * the same Maps afterward, so there is no overwrite race in practice.
   */
  bootstrapOrderbook(
    yes: readonly [number, number][],
    no: readonly [number, number][],
  ): void {
    this._yesBook.set(new Map(yes));
    this._noBook.set(new Map(no));
  }

  ngOnDestroy(): void {
    this.disconnect();
  }

  // ── Message handling ──────────────────────────────────────────────────────

  private handleMessage(raw: string): void {
    let envelope: WsEnvelope;
    try {
      envelope = JSON.parse(raw) as WsEnvelope;
    } catch {
      return;
    }

    switch (envelope.type) {
      case 'ticker':
        this.applyTickerUpdate(envelope.msg as WsTickerMsg);
        break;
      case 'orderbook_snapshot':
        this.applyOrderbookSnapshot(envelope.msg as WsOrderbookSnapshot);
        break;
      case 'orderbook_delta':
        this.applyOrderbookDelta(envelope.msg as WsOrderbookDelta);
        break;
      default:
        break;
    }
  }

  private applyTickerUpdate(msg: WsTickerMsg): void {
    if (msg.yes_bid !== undefined) this.yesBid.set(msg.yes_bid);
    if (msg.yes_ask !== undefined) this.yesAsk.set(msg.yes_ask);
    if (msg.last_price !== undefined) this.lastPrice.set(msg.last_price);
    if (msg.volume !== undefined) this.volume.set(msg.volume);
    if (msg.open_interest !== undefined) this.openInterest.set(msg.open_interest);
  }

  private applyOrderbookSnapshot(msg: WsOrderbookSnapshot): void {
    this._yesBook.set(new Map(msg.yes));
    this._noBook.set(new Map(msg.no));
  }

  private applyOrderbookDelta(msg: WsOrderbookDelta): void {
    const bookSignal = msg.side === 'yes' ? this._yesBook : this._noBook;
    const current = bookSignal();
    const updated = new Map(current);

    const existing = updated.get(msg.price) ?? 0;
    const newQty = existing + msg.delta;

    if (newQty <= 0) {
      updated.delete(msg.price);
    } else {
      updated.set(msg.price, newQty);
    }

    bookSignal.set(updated);
  }
}
