import { type Page, type Locator } from '@playwright/test';

export class MetricsPage {
  readonly page: Page;
  readonly searchInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.searchInput = page.locator('[data-testid="metrics-search-input"]');
  }

  async goto() {
    await this.page.goto('/metrics');
  }

  metricLink(metricType: string): Locator {
    return this.page.locator(`[data-testid="metric-link-${metricType}"]`);
  }
}
