import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import type { MarketDetailDTO } from '../../catalog.service';

@Component({
  selector: 'app-market-detail-modal',
  standalone: true,
  imports: [],
  templateUrl: './market-detail-modal.component.html',
  styleUrl: './market-detail-modal.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MarketDetailModalComponent {
  readonly market = input<MarketDetailDTO | null>(null);
  readonly open   = input(false);

  readonly close = output<void>();

  /** Dollar string (e.g. "0.6500") → "65¢" */
  formatDollars(val: string | null | undefined): string {
    if (!val) return '—';
    const n = parseFloat(val);
    if (isNaN(n)) return val;
    return `${Math.round(n * 100)}¢`;
  }

  /** Float string (e.g. "12345.6") → "12.3K" */
  formatFp(val: string | null | undefined): string {
    if (!val) return '—';
    const n = parseFloat(val);
    if (isNaN(n)) return val;
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
    return n.toFixed(0);
  }

  formatTs(ts: string | null | undefined): string {
    if (!ts) return '—';
    try {
      return new Date(ts).toLocaleString();
    } catch {
      return ts;
    }
  }

  statusClass(status: string | null | undefined): string {
    switch (status) {
      case 'open':     return 'badge-open';
      case 'closed':   return 'badge-closed';
      case 'settled':  return 'badge-settled';
      case 'unopened': return 'badge-unopened';
      default:         return 'badge-closed';
    }
  }
}
