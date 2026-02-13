import { type Page, type Locator } from '@playwright/test';

export class SleepPage {
  readonly page: Page;
  readonly lastNight: Locator;
  readonly statAvg: Locator;
  readonly statMin: Locator;
  readonly statMax: Locator;
  readonly weeklyChart: Locator;

  constructor(page: Page) {
    this.page = page;
    this.lastNight = page.locator('[data-testid="sleep-last-night"]');
    this.statAvg = page.locator('[data-testid="sleep-stat-avg"]');
    this.statMin = page.locator('[data-testid="sleep-stat-min"]');
    this.statMax = page.locator('[data-testid="sleep-stat-max"]');
    this.weeklyChart = page.locator('[data-testid="sleep-weekly-chart"]');
  }

  async goto() {
    await this.page.goto('/sleep');
  }
}
