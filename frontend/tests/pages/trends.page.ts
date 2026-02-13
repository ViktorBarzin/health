import { type Page, type Locator } from '@playwright/test';

export class TrendsPage {
  readonly page: Page;
  readonly metric1Select: Locator;
  readonly metric2Select: Locator;
  readonly scatterChart: Locator;

  constructor(page: Page) {
    this.page = page;
    this.metric1Select = page.locator('[data-testid="trends-metric1-select"]');
    this.metric2Select = page.locator('[data-testid="trends-metric2-select"]');
    this.scatterChart = page.locator('[data-testid="trends-scatter-chart"]');
  }

  async goto() {
    await this.page.goto('/trends');
  }
}
