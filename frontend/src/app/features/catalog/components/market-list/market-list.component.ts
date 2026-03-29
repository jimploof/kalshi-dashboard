import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import type { MarketDTO } from '../../catalog.service';

@Component({
  selector: 'app-market-list',
  standalone: true,
  imports: [],
  templateUrl: './market-list.component.html',
  styleUrl: './market-list.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MarketListComponent {
  readonly markets = input<readonly MarketDTO[]>([]);
  readonly loading = input(false);

  readonly marketSelected = output<string>();

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
