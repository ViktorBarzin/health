import { test, expect } from '@playwright/test';
import { LoginPage } from './pages/login.page';
import { loginAsTestUser } from './helpers/auth';

test.describe('Authentication', () => {
  test('login page loads', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await expect(loginPage.submitBtn).toBeVisible();
  });

  test('register link navigates to register page', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.registerLink.click();
    await expect(page).toHaveURL(/\/register/);
  });

  test('test-login works and redirects to dashboard', async ({ page }) => {
    await loginAsTestUser(page);
    await page.goto('/');
    // Should be on dashboard, not redirected to login
    await expect(page.locator('[data-testid="dashboard-activity-rings"]')).toBeVisible({ timeout: 10000 });
  });

  test('logout from settings', async ({ page }) => {
    await loginAsTestUser(page);
    await page.goto('/settings');
    await page.locator('[data-testid="settings-logout-btn"]').click();
    await expect(page).toHaveURL(/\/login/);
  });
});
