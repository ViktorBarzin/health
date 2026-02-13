import { type Page, type Locator } from '@playwright/test';

export class WorkoutsPage {
  readonly page: Page;
  readonly filterType: Locator;
  readonly loadMoreBtn: Locator;

  constructor(page: Page) {
    this.page = page;
    this.filterType = page.locator('[data-testid="workouts-filter-type"]');
    this.loadMoreBtn = page.locator('[data-testid="workouts-load-more-btn"]');
  }

  async goto() {
    await this.page.goto('/workouts');
  }

  workoutRow(id: string): Locator {
    return this.page.locator(`[data-testid="workout-row-${id}"]`);
  }
}
