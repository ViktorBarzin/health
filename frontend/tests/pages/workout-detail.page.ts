import { type Page, type Locator } from '@playwright/test';

export class WorkoutDetailPage {
  readonly page: Page;
  readonly backLink: Locator;
  readonly statDistance: Locator;
  readonly statEnergy: Locator;
  readonly statPace: Locator;
  readonly statDuration: Locator;
  readonly map: Locator;

  constructor(page: Page) {
    this.page = page;
    this.backLink = page.locator('[data-testid="workout-detail-back-link"]');
    this.statDistance = page.locator('[data-testid="workout-stat-distance"]');
    this.statEnergy = page.locator('[data-testid="workout-stat-energy"]');
    this.statPace = page.locator('[data-testid="workout-stat-pace"]');
    this.statDuration = page.locator('[data-testid="workout-stat-duration"]');
    this.map = page.locator('[data-testid="workout-detail-map"]');
  }

  async goto(id: string) {
    await this.page.goto(`/workouts/${id}`);
  }
}
