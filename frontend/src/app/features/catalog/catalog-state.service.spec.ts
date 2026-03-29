import { TestBed } from '@angular/core/testing';
import { describe, it, expect, beforeEach } from 'vitest';

import { CatalogStateService } from './catalog-state.service';

describe('CatalogStateService', () => {
  let service: CatalogStateService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(CatalogStateService);
  });

  it('starts in a fully-reset state', () => {
    expect(service.selectedCategory()).toBeNull();
    expect(service.selectedEventTicker()).toBeNull();
  });

  it('selectCategory sets category and resets event ticker', () => {
    service.selectEvent('E1');
    service.selectCategory('Sports');
    expect(service.selectedCategory()).toBe('Sports');
    expect(service.selectedEventTicker()).toBeNull();
  });

  it('selectCategory replaces a previously selected category', () => {
    service.selectCategory('Sports');
    service.selectCategory('Crypto');
    expect(service.selectedCategory()).toBe('Crypto');
  });

  it('selectEvent sets event ticker without resetting category', () => {
    service.selectCategory('Sports');
    service.selectEvent('E1');
    expect(service.selectedEventTicker()).toBe('E1');
    expect(service.selectedCategory()).toBe('Sports');
  });

  it('resetToRoot clears all selections', () => {
    service.selectCategory('Sports');
    service.selectEvent('E1');
    service.resetToRoot();
    expect(service.selectedCategory()).toBeNull();
    expect(service.selectedEventTicker()).toBeNull();
  });

  it('resetToCategory resets event ticker but preserves category', () => {
    service.selectCategory('Sports');
    service.selectEvent('E1');
    service.resetToCategory();
    expect(service.selectedCategory()).toBe('Sports');
    expect(service.selectedEventTicker()).toBeNull();
  });
});
