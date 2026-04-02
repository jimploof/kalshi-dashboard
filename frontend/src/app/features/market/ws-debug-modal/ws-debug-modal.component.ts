import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
} from '@angular/core';

import { MarketWsService } from '../market-ws.service';

@Component({
  selector: 'app-ws-debug-modal',
  standalone: true,
  imports: [],
  templateUrl: './ws-debug-modal.component.html',
  styleUrl: './ws-debug-modal.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WsDebugModalComponent {
  @Input({ required: true }) ws!: MarketWsService;
  @Output() readonly closed = new EventEmitter<void>();

  close(): void {
    this.closed.emit();
  }

  copyToClipboard(text: string): void {
    navigator.clipboard.writeText(text);
  }

  get diagnosticDump(): string {
    const ws = this.ws;
    return JSON.stringify({
      connected: ws.connected(),
      error: ws.wsError(),
      messageCount: ws.messageCount(),
      lastMessageType: ws.lastMessageType(),
      lastMessageAt: ws.lastMessageAt()?.toISOString() ?? null,
      tickerCount: ws.tickerCount(),
      tickerPulse: ws.tickerPulse(),
      lastTickerAt: ws.lastTickerAt()?.toISOString() ?? null,
      obSnapshotCount: ws.obSnapshotCount(),
      obDeltaCount: ws.obDeltaCount(),
      unknownCount: ws.unknownCount(),
      yesBid: ws.yesBid(),
      yesAsk: ws.yesAsk(),
      lastPrice: ws.lastPrice(),
      volume: ws.volume(),
      openInterest: ws.openInterest(),
      yesBidsDepth: ws.yesBids().length,
      noBidsDepth: ws.noBids().length,
      spread: ws.spread(),
      lastRawSample: ws.lastRawSample(),
      lastTickerSample: ws.lastTickerSample(),
    }, null, 2);
  }
}
