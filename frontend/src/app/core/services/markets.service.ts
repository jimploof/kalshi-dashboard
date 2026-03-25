import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from './api.service';

export type ConnectionStatus = {
  readonly postgres: boolean;
  readonly redis: boolean;
};

export type MarketStatus = {
  readonly status: string;
  readonly message: string;
  readonly markets: readonly string[];
  readonly connections: ConnectionStatus;
};

@Injectable({ providedIn: 'root' })
export class MarketsService {
  private readonly api = inject(ApiService);

  getStatus(): Observable<MarketStatus> {
    return this.api.get<MarketStatus>('/markets/');
  }
}
