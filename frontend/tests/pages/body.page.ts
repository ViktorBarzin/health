import { type Page, type Locator } from '@playwright/test';

export class BodyPage {
  readonly page: Page;
  readonly currentWeight: Locator;
  readonly currentBmi: Locator;
  readonly weightChart: Locator;

  constructor(page: Page) {
    this.page = page;
    this.currentWeight = page.locator('[data-testid="body-current-weight"]');
    this.currentBmi = page.locator('[data-testid="body-current-bmi"]');
    this.weightChart = page.locator('[data-testid="body-weight-chart"]');
  }

  async goto() {
    await this.page.goto('/body');
  }
}
