import { inject, Injectable } from '@angular/core';
import { catchError, Observable, of } from 'rxjs';

import { ApiService } from './api.service';

export type DependencyChecks = {
  readonly postgres: boolean;
  readonly redis: boolean;
};

export type ReadinessStatus = {
  readonly ready: boolean;
  readonly checks: DependencyChecks;
};

@Injectable({ providedIn: 'root' })
export class ReadinessService {
  private readonly api = inject(ApiService);

  getReadiness(): Observable<ReadinessStatus | null> {
    return this.api.get<ReadinessStatus>('/ready').pipe(
      catchError(() => of(null)),
    );
  }
}
