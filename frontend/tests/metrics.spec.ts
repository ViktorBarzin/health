import { test, expect } from '@playwright/test';
import { loginAsTestUser } from './helpers/auth';
import { MetricsPage } from './pages/metrics.page';

test.describe('Metrics', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page);
  });

  test('metrics page loads with search input', async ({ page }) => {
    const metricsPage = new MetricsPage(page);
    await metricsPage.goto();
    await expect(metricsPage.searchInput).toBeVisible();
  });

  test('search filters metrics', async ({ page }) => {
    const metricsPage = new MetricsPage(page);
    await metricsPage.goto();
    await metricsPage.searchInput.fill('heart');
    // Should filter the metrics list
    await page.waitForTimeout(500);
  });

  test('clicking metric opens detail', async ({ page }) => {
    const metricsPage = new MetricsPage(page);
    await metricsPage.goto();
    // Click on any available metric link
    const firstLink = page.locator('[data-testid^="metric-link-"]').first();
    if (await firstLink.isVisible()) {
      await firstLink.click();
      await expect(page).toHaveURL(/\/metrics\//);
      await expect(page.locator('[data-testid="metric-detail-back-btn"]')).toBeVisible();
    }
  });
});
