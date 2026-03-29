import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import type { EventDTO } from '../../catalog.service';

@Component({
  selector: 'app-event-list',
  standalone: true,
  imports: [],
  templateUrl: './event-list.component.html',
  styleUrl: './event-list.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EventListComponent {
  readonly events  = input<readonly EventDTO[]>([]);
  readonly loading = input(false);

  readonly eventSelected = output<string>();

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
