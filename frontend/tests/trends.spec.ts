import { test, expect } from '@playwright/test';
import { loginAsTestUser } from './helpers/auth';
import { TrendsPage } from './pages/trends.page';

test.describe('Trends', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page);
  });

  test('trends page loads with metric selectors', async ({ page }) => {
    const trendsPage = new TrendsPage(page);
    await trendsPage.goto();
    await expect(trendsPage.metric1Select).toBeVisible();
    await expect(trendsPage.metric2Select).toBeVisible();
  });
});
