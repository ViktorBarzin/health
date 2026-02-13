import { test, expect } from '@playwright/test';
import { loginAsTestUser } from './helpers/auth';
import { BodyPage } from './pages/body.page';

test.describe('Body', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page);
  });

  test('body page loads', async ({ page }) => {
    const bodyPage = new BodyPage(page);
    await bodyPage.goto();
    await page.waitForLoadState('networkidle');
  });
});
