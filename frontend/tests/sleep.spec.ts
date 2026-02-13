import { test, expect } from '@playwright/test';
import { loginAsTestUser } from './helpers/auth';
import { SleepPage } from './pages/sleep.page';

test.describe('Sleep', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page);
  });

  test('sleep page loads', async ({ page }) => {
    const sleepPage = new SleepPage(page);
    await sleepPage.goto();
    // Page should load without error
    await page.waitForLoadState('networkidle');
  });
});
