import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgIconComponent, provideIcons } from '@ng-icons/core';
import {
  heroChevronDoubleLeft,
  heroChevronDoubleRight,
  heroChevronDown,
  heroChevronRight,
  heroSquares2x2,
  heroClipboardDocumentList,
  heroChartBar,
  heroCheckBadge,
} from '@ng-icons/heroicons/outline';

import { CatalogService, type CategorySummary } from '../../../../features/catalog/catalog.service';
import { CatalogStateService } from '../../../../features/catalog/catalog-state.service';

@Component({
  selector: 'app-side-nav',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, NgIconComponent],
  providers: [
    provideIcons({
      heroChevronDoubleLeft,
      heroChevronDoubleRight,
      heroChevronDown,
      heroChevronRight,
      heroSquares2x2,
      heroClipboardDocumentList,
      heroChartBar,
      heroCheckBadge,
    }),
  ],
  templateUrl: './side-nav.component.html',
  styleUrl: './side-nav.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SideNavComponent implements OnInit {
  private readonly catalogService = inject(CatalogService);
  private readonly destroyRef = inject(DestroyRef);
  readonly state = inject(CatalogStateService);

  readonly collapsed = signal(false);
  readonly categories = signal<readonly CategorySummary[]>([]);
  readonly categoriesLoading = signal(true);
  readonly catalogExpanded = signal(true);

  ngOnInit(): void {
    this.catalogService
      .getCategories()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: r => {
          this.categories.set(r.categories);
          this.categoriesLoading.set(false);
        },
        error: () => this.categoriesLoading.set(false),
      });
  }

  toggle(): void {
    this.collapsed.update(v => !v);
  }

  toggleCatalog(): void {
    this.catalogExpanded.update(v => !v);
  }

  selectCategory(name: string): void {
    this.state.selectCategory(name);
    if (this.collapsed()) {
      this.collapsed.set(false);
    }
  }
}
