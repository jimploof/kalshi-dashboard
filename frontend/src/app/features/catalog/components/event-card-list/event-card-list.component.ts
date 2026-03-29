import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import type { EventCardSummaryDTO } from '../../catalog.service';

@Component({
  selector: 'app-event-card-list',
  standalone: true,
  imports: [],
  templateUrl: './event-card-list.component.html',
  styleUrl: './event-card-list.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EventCardListComponent {
  readonly cards   = input<readonly EventCardSummaryDTO[]>([]);
  readonly loading = input(false);

  readonly cardSelected = output<string>();

  /** Format a fixed-point string (e.g. "1500.00") with K/M suffix. */
  formatFp(fp: string): string {
    const n = parseFloat(fp);
    if (isNaN(n)) return '—';
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
    return String(Math.round(n));
  }
}
