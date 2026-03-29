import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { NgIconComponent, provideIcons } from '@ng-icons/core';
import { heroTag } from '@ng-icons/heroicons/outline';

import type { SeriesDTO } from '../../catalog.service';

@Component({
  selector: 'app-series-list',
  standalone: true,
  imports: [NgIconComponent],
  providers: [provideIcons({ heroTag })],
  templateUrl: './series-list.component.html',
  styleUrl: './series-list.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SeriesListComponent {
  readonly series  = input<readonly SeriesDTO[]>([]);
  readonly loading = input(false);

  readonly seriesSelected = output<string>();

  formatVolume(v: number): string {
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1_000)     return `${(v / 1_000).toFixed(1)}K`;
    return String(v);
  }
}
