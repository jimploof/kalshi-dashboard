import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  signal,
} from '@angular/core';

import { SignalEventRecord, SignalLifecycleEventRecord } from '../market.service';

@Component({
  selector: 'app-signal-log-modal',
  standalone: true,
  imports: [],
  templateUrl: './signal-log-modal.component.html',
  styleUrl: './signal-log-modal.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SignalLogModalComponent {
  @Input({ required: true }) events: readonly SignalEventRecord[] = [];
  @Input() lifecycleEvents: readonly SignalLifecycleEventRecord[] = [];
  @Input() modeFilter: 'all' | 'strict' | 'fast' | 'open' = 'all';
  @Input({ required: true }) loading = false;
  @Input() error: string | null = null;
  @Input() marketTicker: string | null = null;

  @Output() readonly closed = new EventEmitter<void>();
  @Output() readonly refreshRequested = new EventEmitter<void>();
  @Output() readonly modeFilterChanged = new EventEmitter<'all' | 'strict' | 'fast' | 'open'>();

  readonly expandedIds = signal<readonly number[]>([]);

  close(): void {
    this.closed.emit();
  }

  refresh(): void {
    this.refreshRequested.emit();
  }

  setModeFilter(mode: 'all' | 'strict' | 'fast' | 'open'): void {
    this.modeFilterChanged.emit(mode);
  }

  toggleExpanded(id: number): void {
    this.expandedIds.update(current =>
      current.includes(id) ? current.filter(v => v !== id) : [...current, id],
    );
  }

  isExpanded(id: number): boolean {
    return this.expandedIds().includes(id);
  }

  formatTimestamp(iso: string): string {
    return new Date(iso).toLocaleString();
  }

  prettyJson(value: unknown): string {
    return JSON.stringify(value ?? {}, null, 2);
  }
}
