import { Injectable, OnDestroy, signal } from '@angular/core';

type WsEnvelope = {
  readonly type: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  readonly msg?: any;
};

type WsTickerMsg = {
  readonly market_ticker?: string;
  readonly last_price?: number | null;
};

@Injectable()
export class EventWsService implements OnDestroy {
  private readonly sockets = new Map<string, WebSocket>();

  readonly tickerPulse = signal(0);
  readonly livePrices = signal<Readonly<Record<string, number | null>>>({});

  connectMany(tickers: readonly string[]): void {
    const desired = new Set(tickers);

    for (const [ticker, ws] of this.sockets) {
      if (!desired.has(ticker)) {
        ws.close();
        this.sockets.delete(ticker);
      }
    }

    for (const ticker of desired) {
      if (this.sockets.has(ticker)) continue;
      this.connectOne(ticker);
    }
  }

  disconnectAll(): void {
    for (const ws of this.sockets.values()) {
      ws.close();
    }
    this.sockets.clear();
    this.livePrices.set({});
  }

  ngOnDestroy(): void {
    this.disconnectAll();
  }

  private connectOne(ticker: string): void {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${location.host}/ws/market/${encodeURIComponent(ticker)}`;
    const ws = new WebSocket(url);

    ws.onmessage = (event: MessageEvent<string>) => {
      this.handleMessage(ticker, event.data);
    };

    ws.onclose = () => {
      if (this.sockets.get(ticker) === ws) {
        this.sockets.delete(ticker);
      }
    };

    this.sockets.set(ticker, ws);
  }

  private handleMessage(expectedTicker: string, raw: string): void {
    let envelope: WsEnvelope;
    try {
      envelope = JSON.parse(raw) as WsEnvelope;
    } catch {
      return;
    }

    if (envelope.type !== 'ticker') return;

    const msg = envelope.msg as WsTickerMsg | undefined;
    if (!msg || msg.last_price === undefined) return;

    const ticker = msg.market_ticker ?? expectedTicker;
    this.livePrices.update(current => ({
      ...current,
      [ticker]: msg.last_price ?? null,
    }));

    // Force downstream effects even when price value is unchanged.
    this.tickerPulse.update(v => v + 1);
  }
}
