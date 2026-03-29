import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';

import { DebugModalComponent } from './debug-modal.component';
import { DebugService } from '../../../services/debug.service';
import { ReadinessService } from '../../../services/readiness.service';

@Component({
  selector: 'app-footer',
  standalone: true,
  imports: [DebugModalComponent],
  templateUrl: './footer.component.html',
  styleUrl: './footer.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FooterComponent implements OnInit {
  private readonly readiness = inject(ReadinessService);
  readonly debug = inject(DebugService);
  readonly status = toSignal(this.readiness.getReadiness());

  readonly debugModalOpen = signal(false);

  ngOnInit(): void {
    this.debug.startPolling();
  }

  openDebugModal(): void {
    this.debugModalOpen.set(true);
  }

  closeDebugModal(): void {
    this.debugModalOpen.set(false);
  }
}
