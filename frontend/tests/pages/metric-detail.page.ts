import { type Page, type Locator } from '@playwright/test';

export class MetricDetailPage {
  readonly page: Page;
  readonly backBtn: Locator;
  readonly chart: Locator;
  readonly statAvg: Locator;
  readonly statMin: Locator;
  readonly statMax: Locator;
  readonly statCount: Locator;
  readonly statTrend: Locator;

  constructor(page: Page) {
    this.page = page;
    this.backBtn = page.locator('[data-testid="metric-detail-back-btn"]');
    this.chart = page.locator('[data-testid="metric-detail-chart"]');
    this.statAvg = page.locator('[data-testid="metric-stat-avg"]');
    this.statMin = page.locator('[data-testid="metric-stat-min"]');
    this.statMax = page.locator('[data-testid="metric-stat-max"]');
    this.statCount = page.locator('[data-testid="metric-stat-count"]');
    this.statTrend = page.locator('[data-testid="metric-stat-trend"]');
  }

  async goto(metricType: string) {
    await this.page.goto(`/metrics/${metricType}`);
  }
}
