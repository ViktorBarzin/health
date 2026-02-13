import { test, expect } from '@playwright/test';
import { loginAsTestUser } from './helpers/auth';

test.describe('Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page);
  });

  test('all sidebar links navigate correctly', async ({ page }) => {
    await page.goto('/');
    const navItems = [
      { testid: 'sidebar-nav-metrics', url: '/metrics' },
      { testid: 'sidebar-nav-workouts', url: '/workouts' },
      { testid: 'sidebar-nav-sleep', url: '/sleep' },
      { testid: 'sidebar-nav-body', url: '/body' },
      { testid: 'sidebar-nav-trends', url: '/trends' },
      { testid: 'sidebar-nav-settings', url: '/settings' },
      { testid: 'sidebar-nav-dashboard', url: '/' },
    ];

    for (const item of navItems) {
      await page.locator(`[data-testid="${item.testid}"]`).click();
      await expect(page).toHaveURL(new RegExp(item.url === '/' ? '/$' : item.url));
    }
  });

  test('date picker is visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="daterange-preset-30d"]')).toBeVisible();
  });
});
