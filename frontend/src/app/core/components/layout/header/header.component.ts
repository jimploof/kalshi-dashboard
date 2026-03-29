import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NgIconComponent, provideIcons } from '@ng-icons/core';
import { heroBolt } from '@ng-icons/heroicons/outline';

import { ReadinessService } from '../../../services/readiness.service';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [NgIconComponent],
  providers: [provideIcons({ heroBolt })],
  templateUrl: './header.component.html',
  styleUrl: './header.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HeaderComponent {
  private readonly readiness = inject(ReadinessService);
  readonly status = toSignal(this.readiness.getReadiness());
}
