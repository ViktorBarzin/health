import { test, expect } from '@playwright/test';
import { loginAsTestUser } from './helpers/auth';

const pages = [
  { name: 'dashboard', path: '/' },
  { name: 'metrics', path: '/metrics' },
  { name: 'workouts', path: '/workouts' },
  { name: 'sleep', path: '/sleep' },
  { name: 'body', path: '/body' },
  { name: 'trends', path: '/trends' },
  { name: 'settings', path: '/settings' },
];

test.describe('Visual Regression', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page);
  });

  for (const p of pages) {
    test(`${p.name} page screenshot`, async ({ page }) => {
      await page.goto(p.path);
      await page.waitForLoadState('networkidle');
      await expect(page).toHaveScreenshot(`${p.name}.png`, {
        maxDiffPixelRatio: 0.01,
        fullPage: true,
      });
    });
  }

  test('login page screenshot', async ({ page }) => {
    await page.goto('/login');
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveScreenshot('login.png', {
      maxDiffPixelRatio: 0.01,
      fullPage: true,
    });
  });

  test('register page screenshot', async ({ page }) => {
    await page.goto('/register');
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveScreenshot('register.png', {
      maxDiffPixelRatio: 0.01,
      fullPage: true,
    });
  });
});
