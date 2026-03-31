import { Routes } from '@angular/router';

import { CatalogComponent } from './features/catalog/catalog.component';
import { MarketViewComponent } from './features/market/market-view/market-view.component';

export const routes: Routes = [
  { path: 'catalog', component: CatalogComponent },
  { path: 'market/:ticker', component: MarketViewComponent },
  { path: '', redirectTo: 'catalog', pathMatch: 'full' },
];
