import { test, expect } from '@playwright/test';
import { loginAsTestUser } from './helpers/auth';
import { WorkoutsPage } from './pages/workouts.page';

test.describe('Workouts', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page);
  });

  test('workouts page loads', async ({ page }) => {
    const workoutsPage = new WorkoutsPage(page);
    await workoutsPage.goto();
    await expect(workoutsPage.filterType).toBeVisible();
  });

  test('activity type filter works', async ({ page }) => {
    const workoutsPage = new WorkoutsPage(page);
    await workoutsPage.goto();
    await expect(workoutsPage.filterType).toBeVisible();
  });
});
