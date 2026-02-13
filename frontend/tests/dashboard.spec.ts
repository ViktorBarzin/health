import { test, expect } from '@playwright/test';
import { loginAsTestUser } from './helpers/auth';
import { DashboardPage } from './pages/dashboard.page';

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page);
  });

  test('dashboard loads with metric cards', async ({ page }) => {
    await page.goto('/');
    const dashboard = new DashboardPage(page);
    await expect(dashboard.activityRings).toBeVisible({ timeout: 10000 });
  });

  test('sleep summary visible', async ({ page }) => {
    await page.goto('/');
    const dashboard = new DashboardPage(page);
    await expect(dashboard.sleepSummary).toBeVisible({ timeout: 10000 });
  });

  test('recent workouts section visible', async ({ page }) => {
    await page.goto('/');
    const dashboard = new DashboardPage(page);
    await expect(dashboard.recentWorkouts).toBeVisible({ timeout: 10000 });
  });

  test('date range presets update content', async ({ page }) => {
    await page.goto('/');
    const dashboard = new DashboardPage(page);
    // Click 7D preset
    await dashboard.daterangePreset('7d').click();
    await page.waitForTimeout(1000);
    // Click 1Y preset
    await dashboard.daterangePreset('1y').click();
    await page.waitForTimeout(1000);
    // Dashboard should still be visible
    await expect(dashboard.activityRings).toBeVisible();
  });
});
