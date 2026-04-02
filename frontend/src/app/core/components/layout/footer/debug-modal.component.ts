import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  inject,
  Input,
  OnDestroy,
  OnInit,
  Output,
} from '@angular/core';

import { DebugService, DebugStatus, KalshiCallRecord, CacheLookupRecord, SnapshotBuildRecord, ConnectivityStatus } from '../../../services/debug.service';

@Component({
  selector: 'app-debug-modal',
  standalone: true,
  imports: [],
  templateUrl: './debug-modal.component.html',
  styleUrl: './debug-modal.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DebugModalComponent implements OnInit, OnDestroy {
  @Output() readonly closed = new EventEmitter<void>();

  readonly debug = inject(DebugService);

  ngOnInit(): void {
    this.debug.startPolling();
  }

  ngOnDestroy(): void {
    // Keep polling so the footer chip stays updated after modal close.
  }

  close(): void {
    this.closed.emit();
  }

  formatMs(ms: number | null): string {
    if (ms === null) return '—';
    return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms.toFixed(0)}ms`;
  }

  formatAge(seconds: number | null): string {
    if (seconds === null) return '—';
    return seconds >= 60 ? `${(seconds / 60).toFixed(1)}m` : `${seconds.toFixed(0)}s`;
  }

  formatTs(iso: string | null): string {
    if (!iso) return '—';
    return new Date(iso).toLocaleTimeString();
  }

  trackByEndpoint(_: number, call: KalshiCallRecord): string {
    return call.started_at;
  }

  trackByCacheLookup(_: number, record: CacheLookupRecord): string {
    return record.timestamp;
  }

  trackByBuild(_: number, record: SnapshotBuildRecord): string {
    return record.started_at;
  }
}
